import asyncio
from collections.abc import Callable, Coroutine
import hashlib
from itertools import chain
import random
from typing import Any, TypeVar
from abc import ABC, abstractmethod
from pathlib import Path
import zlib
from typing_extensions import ParamSpec, override

import httpx

from _download_github_directory import DownloadTask, collect_directory_tasks
from _swf_handle import (
	AMF3Reader,
	extract_binary_data,
	extract_swf_data,
)


HTML5_BASE_URL = "https://seerh5.61.com"
HTML5_VERSION_CHECK_URL = f"{HTML5_BASE_URL}/version/version.json?t={random.uniform(0.01, 0.09)}"
UNITY_VERSION_CHECK_URL = "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/package-manifests/ConfigPackage.json"

T_ParamSpec = ParamSpec('T_ParamSpec')
T_Retval = TypeVar('T_Retval')

def run_async_in_sync(
	async_func: Callable[T_ParamSpec, Coroutine[Any, Any, T_Retval]],
	*args: T_ParamSpec.args,
	**kwargs: T_ParamSpec.kwargs,
) -> T_Retval:
	"""在同步函数中运行异步函数"""
	loop = asyncio.get_event_loop()
	return loop.run_until_complete(async_func(*args, **kwargs))


def get_file_hash(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


def write_to_github_output(name: str, value: str) -> None:
	"""写入输出到 GitHub Actions 的 GITHUB_OUTPUT 文件
	
	Args:
		name: 输出变量的名称
		value: 输出变量的值
	"""
	import os
	
	github_output = os.getenv("GITHUB_OUTPUT")
	if not github_output:
		print("警告：未找到 GITHUB_OUTPUT 环境变量")
		return
	
	with open(github_output, "a", encoding="utf-8") as f:
		# 如果值包含换行符，使用 EOF 格式（多行输出）
		if "\n" in value:
			f.write(f"{name}<<EOF\n")
			f.write(value)
			f.write("\nEOF\n")
		else:
			f.write(f"{name}={value}\n")


def handle_item_xml_info(data: list[dict]) -> dict:
	result = {}
	for obj in data:
		cat_obj = obj["catObj"]
		cat_id = cat_obj["ID"]
		if cat_id not in result:
			cat_obj["item"] = []
			result[cat_id] = cat_obj
		
		item: Any = obj["itemObj"]
		item["CatID"] = cat_id
		cat_obj["item"].append(item)

	return {"root": add_at_prefix_to_keys({"items": list(result.values())})}


def handle_gold_product_xml_info(data: list[dict]) -> dict:
	def _delete_class(obj: dict) -> dict:
		obj.pop("__class__")
		return obj

	return {"root": add_at_prefix_to_keys({"item": [_delete_class(obj) for obj in data]})}


def handle_skill_xml_info(data: list[dict]) -> dict:
	return {"root": add_at_prefix_to_keys({"item": data})}


AMF3_DATA_HANDLERS = {
	'com.robot.core.config.xml.ItemXMLInfo_xmlClass': handle_item_xml_info,
	'com.robot.core.config.xml.GoldProductXMLInfo_xmlClass': handle_gold_product_xml_info,
	'com.robot.core.config.xml.SkillXMLInfo_xmlClass': handle_skill_xml_info,
}

T = TypeVar('T', bound=dict[str, Any] | list[Any] | Any)

def add_at_prefix_to_keys(data: T) -> T:
	"""为字典及嵌套字典中所有的 key 添加@前缀，除非值是列表（但是为列表中的字典添加@前缀）"""
	if isinstance(data, dict):
		result = {}
		for key, value in data.items():
			# 为 key 添加@前缀
			new_key = f"@{key}"
			
			if isinstance(value, list):
				# 如果值是列表，递归处理列表中的每个元素
				result[key] = [add_at_prefix_to_keys(item) for item in value]
			elif isinstance(value, dict):
				# 如果值是字典，递归处理
				result[new_key] = add_at_prefix_to_keys(value)
			else:
				# 其他类型直接赋值
				result[new_key] = value
		return result  # type: ignore
	elif isinstance(data, list):
		# 如果是列表，递归处理每个元素
		return [add_at_prefix_to_keys(item) for item in data]  # type: ignore
	else:
		# 其他类型直接返回
		return data


def dict_to_xml(data: dict) -> str:
	import xmltodict
	return xmltodict.unparse(
		data,
		pretty=True,
		full_document=False
	)


class Platform(ABC):
	VERSION_FILE_NAME = ".version"
	
	def __init__(self, work_dir: Path) -> None:
		super().__init__()
		self.work_dir = work_dir
		self.version_file_path = work_dir / self.VERSION_FILE_NAME
		self.work_dir.mkdir(parents=True, exist_ok=True)

	@abstractmethod
	def get_remote_version(self) -> str:
		pass

	@abstractmethod
	def get_configs(self) -> None:
		pass

	def get_local_version(self) -> str:
		if not self.version_file_path.exists():
			raise FileNotFoundError(f"{self.version_file_path} 不存在")
		return self.version_file_path.read_text().strip()
	
	def save_remote_version(self) -> None:
		self.version_file_path.write_text(self.get_remote_version())
	
	def check_update(self) -> bool:
		try:
			local_version = self.get_local_version()
		except FileNotFoundError:
			return True
		return local_version != self.get_remote_version()


class Flash(Platform):
	@staticmethod
	def extract_configs_from_swf(swf: bytes) -> dict[str, bytes]:
		decompressed = zlib.decompress(swf[7:])
		swf_data = extract_swf_data(decompressed)
		return extract_binary_data(swf_data)

	def _get_coredll_swf(self) -> bytes:
		response = httpx.get(
			url="https://seer.61.com/dll/RobotCoreDLL.swf",
			params={"t": random.uniform(0.01, 0.09)}
		)
		response.raise_for_status()
		return response.content

	def _get_prexml_swf(self) -> bytes:
		response = httpx.get(
			url="https://seer.61.com/resource/xml/prexml.swf",
			params={"t": random.uniform(0.01, 0.09)}
		)
		response.raise_for_status()
		return response.content

	@override
	def get_remote_version(self) -> str:
		coredll_swf = self._get_coredll_swf()
		prexml_swf = self._get_prexml_swf()
		file_hashs = coredll_swf + prexml_swf
		return get_file_hash(file_hashs)

	def get_coredll_configs(self) -> None:
		import re

		swf = self._get_coredll_swf()
		swf_configs = self.extract_configs_from_swf(swf)
		for key, value in swf_configs.items():
			if value[:2] == b'\x78\xda':
				print(f"识别到压缩数据 {key}，解压中...")
				value = zlib.decompress(value)
				value = AMF3Reader(value).read_object()
				if handler := AMF3_DATA_HANDLERS.get(key):
					value = handler(value)
				value = dict_to_xml(value)
				value = value.encode("utf-8")
			filename = re.sub(
				r'(_?(xmlclass|xmlcls)|com.robot.core.)', '', key, flags=re.IGNORECASE
			)
			filename = filename.strip('_')
			Path(f"{self.work_dir}/{filename}.xml").write_bytes(value)
	
	def get_prexml_configs(self) -> None:
		import zipfile
		import io

		swf = self._get_prexml_swf()
		prexml_dir = Path(self.work_dir) / "prexml"
		prexml_dir.mkdir(parents=True, exist_ok=True)
		with zipfile.ZipFile(io.BytesIO(swf)) as zip_file:
			for file_info in zip_file.infolist():
				xml_data = zip_file.read(file_info)
				filename = prexml_dir / file_info.filename
				filename.write_bytes(xml_data)
	
	@override
	def get_configs(self) -> None:
		self.get_coredll_configs()
		self.get_prexml_configs()


async def download_data_async(
	tasks: list[DownloadTask],
	output_dir: Path = Path("."),
	max_concurrency: int = 20,
	max_retries: int = 2,
	**client_kwargs: Any,
) -> None:
	async with (
		asyncio.Semaphore(max_concurrency),
		httpx.AsyncClient(**client_kwargs) as client,
	):
		for url, filename in tasks:
			file_path = output_dir / filename
			file_path.parent.mkdir(parents=True, exist_ok=True)
			attempt = 0
			backoff_seconds = 0.5
			while True:
				try:
					response = await client.get(url)
					response.raise_for_status()
					file_path.write_bytes(response.content)
					break
				except httpx.HTTPStatusError as e:
					print(f"{url} 下载失败，状态码：{e.response.status_code}")
					break
				except httpx.HTTPError as e:
					attempt += 1
					if attempt > max_retries:
						raise e
					await asyncio.sleep(backoff_seconds)
					backoff_seconds *= 2

	print(f"下载完成：{output_dir}, 共下载 {len(tasks)} 个文件")


class HTML5(Platform):
	def get_version_json(self) -> dict[str, Any]:
		response = httpx.get(url=HTML5_VERSION_CHECK_URL)
		response.raise_for_status()
		return response.json()

	@override
	def get_remote_version(self) -> str:
		return str(self.get_version_json()["version"])

	@override
	def get_configs(self) -> None:
		def build_tasks(tree: dict[str, Any], path_parts: list[str]) -> list[DownloadTask]:
			tasks_local: list[DownloadTask] = []
			for key, value in tree.items():
				if isinstance(value, dict):
					tasks_local.extend(build_tasks(value, path_parts + [key]))
				elif isinstance(value, str):
					effective_dirs = path_parts[1:] if len(path_parts) > 1 else []
					path = (
						'/'.join(chain(effective_dirs, [value]))
						if effective_dirs else value
					)
					url = httpx.URL(f'{HTML5_BASE_URL}/{path}')
					filename = Path(path).with_name(key)
					filename = filename.relative_to('resource', 'config')
					tasks_local.append(DownloadTask(url, filename))

			return tasks_local

		version_json = self.get_version_json()
		tasks = build_tasks(
			version_json['files']['resource']['config'],
			['files', 'resource', 'config']
		)
		run_async_in_sync(download_data_async, tasks, output_dir=self.work_dir)


class Unity(Platform):
	@override
	def get_remote_version(self) -> str:
		response = httpx.get(url=UNITY_VERSION_CHECK_URL)
		response.raise_for_status()
		return response.json()["version"]

	@override
	def get_configs(self) -> None:
		from solaris import parse
		parsers= parse.import_parser_classes()
		temp_dir = Path("unity_temp")
		temp_dir.mkdir(parents=True, exist_ok=True)
		tasks = collect_directory_tasks(
			client=httpx.Client(),
			owner="SeerAPI",
			repo="seer-unity-assets",
			path="newseer/assets/game/configs/bytes",
			root_path="newseer/assets/game/configs/bytes",
			ref="main",
		)
		run_async_in_sync(download_data_async, tasks, output_dir=temp_dir)
		print(f"开始解析 {temp_dir} 中的文件")
		parse.run_all_parser(
			parsers,
			source_dir=temp_dir,
			output_dir=self.work_dir,
		)


def main() -> None:
	from git import Repo
	from datetime import datetime
	from pytz import timezone

	repo = Repo(".")
	config_writer = repo.config_writer()
	config_writer.set_value("user", "name", "github-actions[bot]")
	config_writer.set_value("user", "email", "github-actions[bot]@users.noreply.github.com")
	config_writer.release()
	# 记录当前的 HEAD commit
	initial_head = repo.head.commit

	platforms: list[tuple[str, Platform]] = [
		("flash", Flash(Path("flash"))),
		("html5", HTML5(Path("html5"))),
		("unity", Unity(Path("unity"))),
	]
	for name, platform in platforms:
		print(f"当前版本：{platform.get_local_version()}")
		remote_version = platform.get_remote_version()
		if not platform.check_update():
			print(f"{platform.work_dir} 已是最新版本")
			continue

		print(f"{platform.work_dir} 更新中...")
		platform.get_configs()
		platform.save_remote_version()
		time_str = datetime.now(timezone("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%SUTC%z")
		repo.index.add([platform.work_dir])
		repo.index.commit(
			f"{name}: Update to {remote_version} | Time: {time_str}"
		)
	
	# 检查 HEAD 是否改变（即是否有新的 commit）
	if repo.head.commit == initial_head:
		print("没有更新，跳过推送")
		write_to_github_output("HAS_UPDATE", "false")
		return
	else:
		print("推送本地提交...")
		repo.remotes[0].push()
		write_to_github_output("HAS_UPDATE", "true")

if __name__ == "__main__":
	main()
