#!/usr/bin/env python3
"""使用 GitHub Contents API 下载仓库中某个目录下的所有文件。"""

from pathlib import Path
from typing import NamedTuple, Optional

import httpx

class DownloadTask(NamedTuple):
	url: httpx.URL
	filename: Path


GITHUB_API_ROOT = "https://api.github.com"


class GitHubDownloadError(Exception):
    """表示下载目录时出现的错误。"""


def build_client(token: Optional[str]) -> httpx.Client:
    """构建带有可选鉴权信息的 httpx 客户端。"""

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "seerapi-download-github-directory",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
    return httpx.Client(headers=headers, timeout=timeout)


def ensure_relative_path(full_path: Path, root_path: Optional[str]) -> Path:
    """计算文件相对于根目录的路径。"""

    if root_path:
        try:
            return full_path.relative_to(root_path)
        except ValueError as exc:
            raise GitHubDownloadError(
                f"无法将 {full_path} 转换为相对路径（根：{root_path}）"
            ) from exc
    return full_path


def _create_task_from_item(item: dict, root_path: Optional[str]) -> DownloadTask:
    """从 GitHub API 返回的文件条目构造下载任务。"""

    download_url = item.get("download_url")
    if not download_url:
        raise GitHubDownloadError(f"条目 {item.get('path')} 缺少下载链接，无法处理。")

    relative_path = ensure_relative_path(Path(item["path"]), root_path)
    return DownloadTask(url=httpx.URL(download_url), filename=relative_path)


def handle_rate_limit(response: httpx.Response) -> None:
    """根据响应判断是否触发了速率限制。"""

    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        reset_at = response.headers.get("X-RateLimit-Reset")
        raise GitHubDownloadError(
            "GitHub API 速率限制已耗尽，请稍后再试或提供具有更高额度的令牌。"
            + (f"（重置时间戳：{reset_at}）" if reset_at else "")
        )


def collect_directory_tasks(
    client: httpx.Client,
    owner: str,
    repo: str,
    path: str,
    root_path: Optional[str],
    ref: str,
) -> list[DownloadTask]:
    """递归创建 GitHub 目录及其子项的下载任务。

    参数：
        client: 已配置鉴权和超时的 httpx 客户端。
        owner: 仓库拥有者（组织或用户）。
        repo: 仓库名称。
        path: 需要遍历的仓库内目录路径。
        root_path: 用于计算相对路径的目录根；用于保持本地目录结构。
        ref: 目标分支、标签或提交 SHA。

    异常：
        GitHubDownloadError: 当目录不存在、条目类型不受支持或触发速率限制时抛出。
        httpx.HTTPError: 当 API 请求失败时由调用方捕获。
    """

    effective_root = root_path or path

    api_url = f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/contents/{path}"
    response = client.get(api_url, params={"ref": ref})
    if response.status_code == 404:
        raise GitHubDownloadError(
            f"未找到路径：{owner}/{repo}@{ref}:{path}。请检查仓库、分支或目录是否存在。"
        )

    handle_rate_limit(response)
    response.raise_for_status()

    payload = response.json()
    tasks: list[DownloadTask] = []
    if isinstance(payload, dict):
        if payload.get("type") == "file":
            tasks.append(_create_task_from_item(payload, effective_root))
            return tasks
        raise GitHubDownloadError(
            f"不支持的条目类型：{payload.get('type')}（路径：{payload.get('path')}）。"
        )

    for item in payload:
        item_type = item.get("type")
        item_path = item.get("path")

        if item_type == "file":
            tasks.append(_create_task_from_item(item, effective_root))
        elif item_type == "dir":
            tasks.extend(
                collect_directory_tasks(
                    client,
                    owner,
                    repo,
                    item_path,
                    effective_root,
                    ref,
                )
            )
        else:
            print(f"跳过 {item_path}（类型：{item_type}），脚本暂不支持处理。")

    return tasks
