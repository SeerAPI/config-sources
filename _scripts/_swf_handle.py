from datetime import datetime
from typing import Any
from io import BytesIO
import struct
import zlib

# AMF3 数据类型常量
AMF3_UNDEFINED = 0x00
AMF3_NULL = 0x01
AMF3_FALSE = 0x02
AMF3_TRUE = 0x03
AMF3_INTEGER = 0x04
AMF3_DOUBLE = 0x05
AMF3_STRING = 0x06
AMF3_XML_DOC = 0x07
AMF3_DATE = 0x08
AMF3_ARRAY = 0x09
AMF3_OBJECT = 0x0A
AMF3_XML = 0x0B
AMF3_BYTE_ARRAY = 0x0C


class AMF3Reader:
	"""与 ActionScript 3 ByteArray.readObject 兼容的 AMF3 数据读取器"""
	
	def __init__(self, data: bytes):
		self.stream = BytesIO(data)
		self.string_table = []  # 字符串引用表
		self.object_table = []  # 对象引用表
		self.class_table = []   # 类定义引用表
	
	def read_u29(self) -> int:
		"""读取 AMF3 变长整数 (U29)"""
		result = 0
		for i in range(4):
			byte = struct.unpack('B', self.stream.read(1))[0]
			if i == 3:
				result = (result << 8) | byte
			else:
				result = (result << 7) | (byte & 0x7F)
				if (byte & 0x80) == 0:
					break
		return result
	
	def read_string(self) -> str:
		"""读取 AMF3 字符串"""
		u29 = self.read_u29()
		
		# 检查是否为引用
		if (u29 & 1) == 0:
			# 引用现有字符串
			ref = u29 >> 1
			if ref < len(self.string_table):
				return self.string_table[ref]
			else:
				raise ValueError(f"字符串引用越界：{ref}")
		
		# 读取新字符串
		length = u29 >> 1
		if length == 0:
			return ""
		
		string_bytes = self.stream.read(length)
		if len(string_bytes) != length:
			raise ValueError(f"字符串数据不完整，期望{length}字节，实际{len(string_bytes)}字节")
		
		try:
			string_value = string_bytes.decode('utf-8')
		except UnicodeDecodeError:
			string_value = string_bytes.decode('latin-1', errors='replace')
		
		# 非空字符串添加到引用表
		if string_value:
			self.string_table.append(string_value)
		
		return string_value
	
	def read_object(self) -> Any:
		"""读取 AMF3 对象（主入口函数）"""
		type_marker = struct.unpack('B', self.stream.read(1))[0]
		
		if type_marker == AMF3_UNDEFINED:
			return None
		elif type_marker == AMF3_NULL:
			return None
		elif type_marker == AMF3_FALSE:
			return False
		elif type_marker == AMF3_TRUE:
			return True
		elif type_marker == AMF3_INTEGER:
			return self.read_integer()
		elif type_marker == AMF3_DOUBLE:
			return self.read_double()
		elif type_marker == AMF3_STRING:
			return self.read_string()
		elif type_marker == AMF3_XML_DOC or type_marker == AMF3_XML:
			return self.read_xml()
		elif type_marker == AMF3_DATE:
			return self.read_date()
		elif type_marker == AMF3_ARRAY:
			return self.read_array()
		elif type_marker == AMF3_OBJECT:
			return self.read_generic_object()
		elif type_marker == AMF3_BYTE_ARRAY:
			return self.read_byte_array()
		else:
			raise ValueError(f"未知的 AMF3 类型标记：0x{type_marker:02X}")
	
	def read_integer(self) -> int:
		"""读取 AMF3 整数"""
		u29 = self.read_u29()
		# 处理有符号数
		if u29 > 0x0FFFFFFF:
			return u29 - 0x20000000
		return u29
	
	def read_double(self) -> float:
		"""读取 AMF3 双精度浮点数"""
		data = self.stream.read(8)
		if len(data) != 8:
			raise ValueError("双精度浮点数据不完整")
		return struct.unpack('>d', data)[0]  # 大端序
	
	def read_xml(self) -> str:
		"""读取 AMF3 XML 数据"""
		u29 = self.read_u29()
		
		# 检查是否为引用
		if (u29 & 1) == 0:
			ref = u29 >> 1
			if ref < len(self.object_table):
				return self.object_table[ref]
			else:
				raise ValueError(f"XML 引用越界：{ref}")
		
		# 读取 XML 数据
		length = u29 >> 1
		xml_bytes = self.stream.read(length)
		if len(xml_bytes) != length:
			raise ValueError("XML 数据不完整")
		
		try:
			xml_string = xml_bytes.decode('utf-8')
		except UnicodeDecodeError:
			xml_string = xml_bytes.decode('latin-1', errors='replace')
		
		self.object_table.append(xml_string)
		return xml_string
	
	def read_date(self) -> datetime:
		"""读取 AMF3 日期"""
		u29 = self.read_u29()
		
		# 检查是否为引用
		if (u29 & 1) == 0:
			ref = u29 >> 1
			if ref < len(self.object_table):
				return self.object_table[ref]
			else:
				raise ValueError(f"日期引用越界：{ref}")
		
		# 读取时间戳（毫秒）
		timestamp_ms = self.read_double()
		timestamp = timestamp_ms / 1000.0
		
		try:
			date_obj = datetime.fromtimestamp(timestamp)
		except (ValueError, OSError):
			date_obj = datetime.fromtimestamp(0)  # 使用 epoch 作为默认值
		
		self.object_table.append(date_obj)
		return date_obj
	
	def read_array(self) -> list | dict:
		"""读取 AMF3 数组"""
		u29 = self.read_u29()
		
		# 检查是否为引用
		if (u29 & 1) == 0:
			ref = u29 >> 1
			if ref < len(self.object_table):
				return self.object_table[ref]
			else:
				raise ValueError(f"数组引用越界：{ref}")
		
		# 创建数组并添加到引用表
		array = []
		self.object_table.append(array)
		
		length = u29 >> 1
		
		# 读取关联部分（键值对）
		while True:
			key = self.read_string()
			if not key:  # 空字符串表示关联部分结束
				break
			value = self.read_object()
			# 对于关联数组，我们使用字典
			if not isinstance(array, dict):
				# 转换为字典
				dict_array = {}
				for i, item in enumerate(array):
					dict_array[str(i)] = item
				array = dict_array
				self.object_table[-1] = array
				array[key] = value
		
		# 读取密集部分（索引数组）
		if isinstance(array, list):
			for i in range(length):
				array.append(self.read_object())
		else:
			# 字典形式的数组
			for i in range(length):
				array[str(i)] = self.read_object()
		
		return array
	
	def read_generic_object(self) -> dict:
		"""读取 AMF3 通用对象"""
		u29 = self.read_u29()
		
		# 检查是否为引用
		if (u29 & 1) == 0:
			ref = u29 >> 1
			if ref < len(self.object_table):
				return self.object_table[ref]
			else:
				raise ValueError(f"对象引用越界：{ref}")
		
		# 创建对象并添加到引用表
		obj = {}
		self.object_table.append(obj)
		
		# 检查类定义引用
		if (u29 & 2) == 0:
			# 引用现有类定义
			class_ref = (u29 >> 2)
			if class_ref >= len(self.class_table):
				raise ValueError(f"类定义引用越界：{class_ref}")
			class_def = self.class_table[class_ref]
		else:
			# 新类定义
			class_name = self.read_string()
			
			# 读取类特征
			dynamic = (u29 & 8) != 0
			externalizable = (u29 & 4) != 0
			
			if externalizable:
				raise ValueError("不支持外部化对象")
			
			# 读取属性名
			property_count = u29 >> 4
			properties = []
			for _ in range(property_count):
				properties.append(self.read_string())
			
			class_def = {
				'class_name': class_name,
				'dynamic': dynamic,
				'properties': properties
			}
			self.class_table.append(class_def)
		
		# 设置类名
		if class_def['class_name']:
			obj['__class__'] = class_def['class_name']
		
		# 读取密封属性
		for prop_name in class_def['properties']:
			obj[prop_name] = self.read_object()
		
		# 读取动态属性
		if class_def['dynamic']:
			while True:
				key = self.read_string()
				if not key:  # 空字符串表示动态部分结束
					break
				obj[key] = self.read_object()
		
		return obj
	
	def read_byte_array(self) -> bytes:
		"""读取 AMF3 字节数组"""
		u29 = self.read_u29()
		
		# 检查是否为引用
		if (u29 & 1) == 0:
			ref = u29 >> 1
			if ref < len(self.object_table):
				return self.object_table[ref]
			else:
				raise ValueError(f"字节数组引用越界：{ref}")
		
		# 读取字节数组
		length = u29 >> 1
		byte_data = self.stream.read(length)
		if len(byte_data) != length:
			raise ValueError("字节数组数据不完整")
		
		self.object_table.append(byte_data)
		return byte_data


def read_amf3_object(data: bytes) -> Any:
	"""与 ActionScript 3 ByteArray.readObject 兼容的读取函数"""
	try:
		reader = AMF3Reader(data)
		return reader.read_object()
	except Exception as e:
		print(f"AMF3 解析错误：{e}")
		# 尝试作为压缩数据处理
		try:
			if data[:2] == b'\x78\xda':  # zlib 压缩标识
				decompressed = zlib.decompress(data)
				reader = AMF3Reader(decompressed)
				return reader.read_object()
		except:
			pass
		
		# 如果都失败了，返回原始字节数据
		return data


def parse_rect(data, offset):
	"""解析 SWF RECT 结构"""
	# RECT 的第一个字节的前 5 位定义了坐标值的位数
	if offset >= len(data):
		return {}, offset
	
	first_byte = data[offset]
	nbits = (first_byte >> 3)  # 前 5 位
	
	if nbits == 0:
		# 空矩形
		return {
			'xmin': 0, 'xmax': 0, 'ymin': 0, 'ymax': 0,
			'width': 0, 'height': 0
		}, offset + 1
	
	# 计算 RECT 结构的总位数：5 位 (NBits) + 4 * NBits 位 (坐标)
	total_bits = 5 + 4 * nbits
	total_bytes = (total_bits + 7) // 8  # 向上取整
	
	if offset + total_bytes > len(data):
		return {}, offset
	
	# 提取完整的位序列
	bit_data = 0
	for i in range(total_bytes):
		if offset + i < len(data):
			bit_data = (bit_data << 8) | data[offset + i]
	
	# 移除前 5 位的 NBits 字段
	bit_data = bit_data & ((1 << (total_bits - 5)) - 1)
	
	# 提取 4 个坐标值
	coords = []
	for i in range(4):
		shift = (3 - i) * nbits
		mask = (1 << nbits) - 1
		value = (bit_data >> shift) & mask
		
		# 处理有符号数（如果最高位为 1，则为负数）
		if value & (1 << (nbits - 1)):
			value = value - (1 << nbits)
		
		coords.append(value)
	
	xmin, xmax, ymin, ymax = coords
	
	return {
		'xmin': xmin, 'xmax': xmax, 'ymin': ymin, 'ymax': ymax,
		'width': xmax - xmin, 'height': ymax - ymin
	}, offset + total_bytes


def parse_swf_header(data):
	"""解析 SWF 文件头（支持版本 14 等高版本）"""
	if len(data) < 8:
		raise ValueError("SWF 文件头数据不足")
	
	# 读取签名（FWS 或 CWS）
	signature = data[:3].decode('ascii')
	
	# 读取版本
	version = struct.unpack('<B', data[3:4])[0]
	
	# 读取文件大小
	file_size = struct.unpack('<I', data[4:8])[0]
	
	# 解析 RECT 结构（电影边界）
	rect_info, rect_end = parse_rect(data, 8)
	
	header_info = {
		'signature': signature,
		'version': version,
		'file_size': file_size,
		'compressed': signature == 'CWS',
		'stage_size': rect_info
	}
	
	# 读取帧率和帧数（如果数据足够）
	if rect_end + 4 <= len(data):
		# 帧率：16 位小端序，以 1/256 为单位
		frame_rate_raw = struct.unpack('<H', data[rect_end:rect_end+2])[0]
		frame_rate = frame_rate_raw / 256.0
		
		# 帧数：16 位小端序
		frame_count = struct.unpack('<H', data[rect_end+2:rect_end+4])[0]
		
		header_info.update({
			'frame_rate': frame_rate,
			'frame_count': frame_count,
			'header_size': rect_end + 4
		})
	else:
		header_info['header_size'] = rect_end
	
	return header_info



def decompress_swf(swf_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
	"""解压缩 SWF 文件"""
	# 首先基于前 8 字节获取基本信息
	if len(swf_bytes) < 8:
		raise ValueError("SWF 文件大小不足")
	
	signature = swf_bytes[:3].decode('ascii')
	is_compressed = signature == 'CWS'
	
	if is_compressed:
		# CWS 格式，需要解压缩
		# 前 8 字节（签名 + 版本 + 文件大小）保持不变
		# 从第 8 字节开始的数据需要解压缩
		compressed_data = swf_bytes[8:]
		try:
			decompressed = zlib.decompress(compressed_data)
		except zlib.error as e:
			raise ValueError(f"SWF 解压缩失败：{e}")
		
		# 重建 FWS 格式：前 8 字节 + 解压缩的数据
		new_data = b'FWS' + swf_bytes[3:8] + decompressed
		
		# 解析完整的文件头（使用解压缩后的数据）
		header = parse_swf_header(new_data)
		return new_data, header
	else:
		# FWS 格式，已经是未压缩的
		header = parse_swf_header(swf_bytes)
		return swf_bytes, header


def read_export_asset_name(data: bytes) -> dict[int, str]:
	"""解析 ExportAssets 标签（标签 56）中的资源导出信息"""
	result: dict[int, str] = {}
	stream = BytesIO(data)
	
	try:
		# 读取资源数量
		count = struct.unpack('<H', stream.read(2))[0]
		print(f"ExportAssets 包含 {count} 个资源")
		
		for _ in range(count):
			# 读取字符 ID（2 字节）
			if stream.tell() + 2 > len(data):
				break
			char_id = struct.unpack('<H', stream.read(2))[0]
			
			# 读取符号名称（null 结尾字符串）
			name_bytes = bytearray()
			while stream.tell() < len(data):
				byte = stream.read(1)
				if not byte or byte == b'\x00':
					break
				name_bytes.extend(byte)
			
			try:
				# 尝试 UTF-8 解码
				symbol_name = name_bytes.decode('utf-8')
			except UnicodeDecodeError:
				# 如果 UTF-8 失败，使用 latin-1
				symbol_name = name_bytes.decode('latin-1', errors='replace')
			
			if symbol_name:  # 只添加非空符号名称
				result[char_id] = symbol_name
	
	except struct.error as e:
		print(f"解析 ExportAssets 时出错：{e}")
	except Exception as e:
		print(f"解析 ExportAssets 时发生未知错误：{e}")
	
	return result


def extract_swf_data(swf_bytes: bytes) -> dict[int, list[bytes]]:
	"""提取 SWF 中的数据"""
	# 解压缩 SWF
	swf_data, header = decompress_swf(swf_bytes)
	
	# 使用正确的头部大小
	header_size = header.get('header_size', 8)
	
	# 创建字节流用于解析
	stream = BytesIO(swf_data[header_size:])  # 跳过完整的 SWF 头部
	data_length = len(swf_data) - header_size  # 实际数据长度
	
	# 根据 SWF 标签格式继续解析
	# 每个标签的格式为：标签头 + 数据
	result: dict[int, list[bytes]] = {}
	while stream.tell() < data_length:
		# 检查是否还有足够的字节读取标签头
		remaining_bytes = data_length - stream.tell()
		if remaining_bytes < 2:
			print(f"警告：剩余字节不足以读取标签头 ({remaining_bytes} 字节)")
			break
		
		# 读取标签头 (2 字节)
		tag_header_data = stream.read(2)
		if len(tag_header_data) != 2:
			print(f"警告：标签头读取不完整，只读取了 {len(tag_header_data)} 字节")
			break
			
		tag_header = struct.unpack('<H', tag_header_data)[0]
		tag_type = tag_header >> 6
		tag_length = tag_header & 0x3F
		
		# 处理长格式标签
		if tag_length == 0x3F:
			# 检查是否有足够字节读取长度字段
			if data_length - stream.tell() < 4:
				print("警告：无足够字节读取长格式标签长度")
				break
			
			length_data = stream.read(4)
			if len(length_data) != 4:
				print("警告：长格式标签长度读取不完整")
				break
				
			tag_length = struct.unpack('<I', length_data)[0]
		
		# 检查是否有足够字节读取标签数据
		remaining_bytes = data_length - stream.tell()
		if remaining_bytes < tag_length:
			print(f"警告：标签 {tag_type} 声明长度 {tag_length}，但只剩余 {remaining_bytes} 字节")
			# 读取剩余的所有字节
			tag_length = remaining_bytes
		
		# 读取标签数据
		tag_data = stream.read(tag_length)
		if len(tag_data) != tag_length:
			print(f"警告：标签 {tag_type} 数据读取不完整，期望 {tag_length} 字节，实际读取 {len(tag_data)} 字节")
		
		# 跳过长度为 0 的标签
		if len(tag_data) == 0:
			continue

		# 检查是否为结束标签 (标签类型 0)
		if tag_type == 0:
			print("遇到结束标签，停止解析")
			break

		if tag_type not in result:
			result[tag_type] = []

		result[tag_type].append(tag_data)
	
	return result


def extract_binary_data(swf_data: dict[int, list[bytes]]) -> dict[str, bytes]:
	"""提取 SWF 中的二进制数据"""
	asset_symbol_names = read_export_asset_name(swf_data[56][0])
	result: dict[str, bytes] = {}

	for tag_data in swf_data[87]:
		character_id = struct.unpack('<H', tag_data[:2])[0]
		symbol_name = asset_symbol_names[character_id]
		result[symbol_name] = tag_data[6:]

	return result

