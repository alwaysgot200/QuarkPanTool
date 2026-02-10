import asyncio
import json
import os
import shutil
import random
import re
import sys
import argparse
from typing import Any, Union

import httpx
from prettytable import PrettyTable
from tqdm import tqdm

from quark_login import CONFIG_DIR, QuarkLogin
from utils import (
    custom_print,
    generate_random_code,
    get_datetime,
    get_timestamp,
    read_config,
    safe_copy,
    save_config,
)


class QuarkPanFileManager:
    TEMP_DIR_NAME = "__________temp"

    def __init__(self, headless: bool = False, slow_mo: int = 0) -> None:
        self.headless: bool = headless
        self.slow_mo: int = slow_mo
        self.folder_id: Union[str, None] = None
        self.user: Union[str, None] = "用户A"
        self.pdir_id: Union[str, None] = "0"
        self.dir_name: Union[str, None] = "根目录"
        self.block_size: int = 100
        self.concurrent_files: int = 3
        self.save_folder: str = "output/downloads"
        self.cookies: str = self.get_cookies()
        self.headers: dict[str, str] = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko)"
            " Chrome/94.0.4606.71 Safari/537.36 Core/1.94.225.400 QQBrowser/12.2.5544.400",
            "origin": "https://pan.quark.cn",
            "referer": "https://pan.quark.cn/",
            "accept-language": "zh-CN,zh;q=0.9",
            "cookie": self.cookies,
        }

    def get_cookies(self) -> str:
        quark_login = QuarkLogin(headless=self.headless, slow_mo=self.slow_mo)
        cookies: str = quark_login.get_cookies()
        return cookies

    @staticmethod
    def get_pwd_id(share_url: str) -> str:
        return share_url.split("?")[0].split("/s/")[-1]

    @staticmethod
    def extract_urls(text: str) -> list:
        url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
        return re.findall(url_pattern, text)[0]

    async def get_stoken(self, pwd_id: str, password: str = "") -> str:
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
            "__dt": random.randint(100, 9999),
            "__t": get_timestamp(13),
        }
        api = "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token"
        data = {"pwd_id": pwd_id, "passcode": password}
        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.post(
                api, json=data, params=params, headers=self.headers, timeout=timeout
            )
            json_data = response.json()
            if json_data["status"] == 200 and json_data["data"]:
                stoken = json_data["data"]["stoken"]
            else:
                stoken = ""
                custom_print(f"文件转存失败，{json_data['message']}")
            return stoken

    async def get_detail(
        self, pwd_id: str, stoken: str, pdir_fid: str = "0"
    ) -> str | tuple | None:
        api = "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/detail"
        page = 1
        file_list: list[dict[str, Union[int, str]]] = []

        async with httpx.AsyncClient(verify=False) as client:
            while True:
                params = {
                    "pr": "ucpro",
                    "fr": "pc",
                    "uc_param_str": "",
                    "pwd_id": pwd_id,
                    "stoken": stoken,
                    "pdir_fid": pdir_fid,
                    "force": "0",
                    "_page": str(page),
                    "_size": "50",
                    "_sort": "file_type:asc,updated_at:desc",
                    "__dt": random.randint(200, 9999),
                    "__t": get_timestamp(13),
                }

                timeout = httpx.Timeout(60.0, connect=60.0)
                response = await client.get(
                    api, headers=self.headers, params=params, timeout=timeout
                )
                json_data = response.json()

                is_owner = json_data["data"]["is_owner"]
                _total = json_data["metadata"]["_total"]
                if _total < 1:
                    return is_owner, file_list

                _size = json_data["metadata"]["_size"]  # 每页限制数量
                _count = json_data["metadata"]["_count"]  # 当前页数量

                _list = json_data["data"]["list"]

                for file in _list:
                    d: dict[str, Union[int, str]] = {
                        "fid": file["fid"],
                        "file_name": file["file_name"],
                        "file_type": file["file_type"],
                        "dir": file["dir"],
                        "pdir_fid": file["pdir_fid"],
                        "include_items": file.get("include_items", ""),
                        "share_fid_token": file["share_fid_token"],
                        "status": file["status"],
                    }
                    file_list.append(d)
                if _total <= _size or _count < _size:
                    return is_owner, file_list

                page += 1

    async def get_sorted_file_list(
        self, pdir_fid="0", page="1", size="100", fetch_total="false", sort=""
    ) -> dict[str, Any]:
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
            "pdir_fid": pdir_fid,
            "_page": page,
            "_size": size,
            "_fetch_total": fetch_total,
            "_fetch_sub_dirs": "1",
            "_sort": sort,
            "__dt": random.randint(100, 9999),
            "__t": get_timestamp(13),
        }

        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.get(
                "https://drive-pc.quark.cn/1/clouddrive/file/sort",
                params=params,
                headers=self.headers,
                timeout=timeout,
            )
            json_data = response.json()
            return json_data

    async def get_user_info(self) -> str:
        # 1. Primary Validation: Use file list API (more reliable)
        try:
            file_list_check = await self.get_sorted_file_list(size="1")
            if file_list_check.get("code") != 0:
                custom_print(
                    f"Cookie验证失败 (文件列表接口返回错误): {file_list_check}",
                    error_msg=True,
                )
                sys.exit(101)  # Exit code 101: Cookie Invalid
        except Exception as e:
            custom_print(f"Cookie验证过程中发生错误: {e}", error_msg=True)
            sys.exit(101)

        # 2. Optional: Get User Nickname (Best Effort)
        params = {
            "fr": "pc",
            "platform": "pc",
        }
        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            try:
                response = await client.get(
                    "https://pan.quark.cn/account/info",
                    params=params,
                    headers=self.headers,
                    timeout=timeout,
                )
                json_data = response.json()

                # Try to extract nickname if possible, but don't fail if structure varies
                if json_data.get("data") and isinstance(json_data["data"], dict):
                    return json_data["data"].get("nickname", "Quark User")

            except Exception:
                pass  # Ignore nickname fetch errors if cookie is already verified

        return "Quark User"

    async def create_dir(
        self, pdir_name="新建文件夹", update_config=True
    ) -> Union[str, None]:
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
            "__dt": random.randint(100, 9999),
            "__t": get_timestamp(13),
        }

        json_data = {
            "pdir_fid": "0",
            "file_name": pdir_name,
            "dir_path": "",
            "dir_init_lock": False,
        }

        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.post(
                "https://drive-pc.quark.cn/1/clouddrive/file",
                params=params,
                json=json_data,
                headers=self.headers,
                timeout=timeout,
            )
            json_data = response.json()
            if json_data["code"] == 0:
                custom_print(f"根目录下 {pdir_name} 文件夹创建成功！")

                # Only update config and instance state if requested
                # This prevents interference when create_dir is used for other purposes
                if update_config:
                    new_state = {
                        "user": self.user,
                        "pdir_id": json_data["data"]["fid"],
                        "dir_name": pdir_name,
                    }
                    save_config(
                        "output/state.json",
                        content=json.dumps(new_state, ensure_ascii=False),
                    )
                    global to_dir_id
                    to_dir_id = json_data["data"]["fid"]

                    # Update instance variables to ensure current session uses new dir
                    self.pdir_id = to_dir_id
                    self.dir_name = pdir_name

                    custom_print(f"自动将保存目录切换至 {pdir_name} 文件夹")

                return json_data["data"]["fid"]
            elif json_data["code"] == 23008:
                custom_print(
                    "文件夹同名冲突，请更换一个文件夹名称后重试", error_msg=True
                )
            else:
                custom_print(f"错误信息：{json_data['message']}", error_msg=True)
        return None

    async def delete_file(self, fid: str) -> bool:
        api = "https://drive-pc.quark.cn/1/clouddrive/file/delete"
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
        }
        data = {"filelist": [fid]}
        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.post(
                api, json=data, params=params, headers=self.headers, timeout=timeout
            )
            json_data = response.json()
            if json_data["code"] == 0:
                custom_print(f"文件夹/文件 (FID: {fid}) 删除成功")
                return True
            else:
                custom_print(f"删除失败: {json_data['message']}", error_msg=True)
                return False

    async def run(
        self,
        input_line: str,
        folder_id: Union[str, None] = None,
        download: bool = False,
    ) -> Union[str, None]:
        self.folder_id = folder_id
        share_url = input_line.strip()
        custom_print(f"文件分享链接：{share_url}")
        match_password = re.search("pwd=(.*?)(?=$|&)", share_url)
        password = match_password.group(1) if match_password else ""
        pwd_id = self.get_pwd_id(input_line).split("#")[0]
        if not pwd_id:
            custom_print("文件分享链接不可为空！", error_msg=True)
            return None
        stoken = await self.get_stoken(pwd_id, password)
        if not stoken:
            return None
        is_owner, data_list = await self.get_detail(pwd_id, stoken)
        files_count = 0
        folders_count = 0
        files_list: list[str] = []
        folders_list: list[str] = []
        folders_map = {}
        files_id_list = []
        file_fid_list = []

        if data_list:
            total_files_count = len(data_list)
            for data in data_list:
                if data["dir"]:
                    folders_count += 1
                    folders_list.append(data["file_name"])
                    folders_map[data["fid"]] = {
                        "file_name": data["file_name"],
                        "pdir_fid": data["pdir_fid"],
                    }
                else:
                    files_count += 1
                    files_list.append(data["file_name"])
                    files_id_list.append((data["fid"], data["file_name"]))

            custom_print(
                f"转存总数：{total_files_count}，文件数：{files_count}，文件夹数：{folders_count} | 支持嵌套"
            )
            custom_print(f"文件转存列表：{files_list}")
            custom_print(f"文件夹转存列表：{folders_list}")

            fid_list = [i["fid"] for i in data_list]
            share_fid_token_list = [i["share_fid_token"] for i in data_list]

            if not self.folder_id:
                custom_print(
                    "保存目录ID不合法，请重新获取，如果无法获取，请输入0作为文件夹ID"
                )
                return None

            if download:
                if is_owner == 0:
                    custom_print(
                        "下载文件必须是自己的网盘内文件，请先将文件转存至网盘中，然后再从自己网盘中获取分享地址进行下载"
                    )
                    return None

                for i in data_list:
                    if i["dir"]:
                        data_list2 = [i]
                        not_dir = False
                        while True:
                            data_list3 = []
                            for i2 in data_list2:
                                custom_print(
                                    f'开始下载：{i2["file_name"]} 文件夹中的{i2["include_items"]}个文件'
                                )
                                is_owner, file_data_list = await self.get_detail(
                                    pwd_id, stoken, pdir_fid=i2["fid"]
                                )

                                # record folder's fid start
                                if file_data_list:
                                    for data in file_data_list:
                                        if data["dir"]:
                                            folders_map[data["fid"]] = {
                                                "file_name": data["file_name"],
                                                "pdir_fid": data["pdir_fid"],
                                            }

                                # record folder's fid stop
                                folder = i["file_name"]
                                fid_list = [i["fid"] for i in file_data_list]
                                await self.quark_file_download(
                                    fid_list, folder=folder, folders_map=folders_map
                                )
                                file_fid_list.extend(
                                    [i for i in file_data_list if not i2["dir"]]
                                )
                                dir_list = [i for i in file_data_list if i["dir"]]

                                if not dir_list:
                                    not_dir = True
                                data_list3.extend(dir_list)
                            data_list2 = data_list3
                            if not data_list2 or not_dir:
                                break

                if len(files_id_list) > 0 or len(file_fid_list) > 0:
                    fid_list = [i[0] for i in files_id_list]
                    file_fid_list.extend(fid_list)
                    # Use self.dir_name if folder is '.' to respect the save directory structure if needed,
                    # but quark_file_download logic handles path construction.
                    # The issue is that files_id_list are from the root of the share.
                    # We should probably pass the correct folder name if we want them organized.
                    # However, the current logic for root files is folder='.'.
                    await self.quark_file_download(
                        file_fid_list, folder=".", folders_map=folders_map
                    )

            else:
                if is_owner == 1:
                    custom_print("网盘中已经存在该文件，无需再次转存")
                    # If already exists, we return the folder_id where it should be (or is).
                    # Since we don't know exactly where it is without searching,
                    # and the user intent is usually "ensure it's in my drive",
                    # returning self.folder_id (the target) is a safe bet for the pipeline to continue.
                    return self.folder_id

                task_id = await self.get_share_save_task_id(
                    pwd_id,
                    stoken,
                    fid_list,
                    share_fid_token_list,
                    to_pdir_fid=self.folder_id,
                )
                res = await self.submit_task(task_id)
                if (
                    res
                    and "data" in res
                    and "save_as" in res["data"]
                    and "to_pdir_fid" in res["data"]["save_as"]
                ):
                    return res["data"]["save_as"]["to_pdir_fid"]

            print()
            return None

    async def get_share_save_task_id(
        self,
        pwd_id: str,
        stoken: str,
        first_ids: list[str],
        share_fid_tokens: list[str],
        to_pdir_fid: str = "0",
    ) -> str:
        task_url = "https://drive.quark.cn/1/clouddrive/share/sharepage/save"
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
            "__dt": random.randint(600, 9999),
            "__t": get_timestamp(13),
        }
        data = {
            "fid_list": first_ids,
            "fid_token_list": share_fid_tokens,
            "to_pdir_fid": to_pdir_fid,
            "pwd_id": pwd_id,
            "stoken": stoken,
            "pdir_fid": "0",
            "scene": "link",
        }

        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.post(
                task_url,
                json=data,
                headers=self.headers,
                params=params,
                timeout=timeout,
            )
            json_data = response.json()
            task_id = json_data["data"]["task_id"]
            custom_print(f"获取任务ID：{task_id}")
            return task_id

    @staticmethod
    async def download_part(
        url: str,
        headers: dict,
        start: int,
        end: int,
        save_path: str,
        pbar: tqdm,
        pbar_lock: asyncio.Lock = None,
    ) -> None:
        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0, read=60.0)
            headers = headers.copy()
            headers["Range"] = f"bytes={start}-{end}"
            retries = 3
            for attempt in range(retries):
                try:
                    async with client.stream(
                        "GET", url, headers=headers, timeout=timeout
                    ) as response:
                        response.raise_for_status()
                        # Use r+b to allow seeking
                        with open(save_path, "r+b") as f:
                            f.seek(start)
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    f.write(chunk)
                                    if pbar:
                                        if pbar_lock:
                                            async with pbar_lock:
                                                pbar.update(len(chunk))
                                        else:
                                            pbar.update(len(chunk))
                    break
                except Exception as e:
                    if attempt == retries - 1:
                        raise e
                    await asyncio.sleep(1)

    @staticmethod
    async def download_file(
        download_url: str,
        save_path: str,
        headers: dict,
        block_size: int = 100,
        semaphore: asyncio.Semaphore = None,
        position_queue: asyncio.Queue = None,
    ) -> None:
        if semaphore:
            await semaphore.acquire()

        position = None
        if position_queue:
            position = await position_queue.get()

        pbar = None
        try:
            # 1. Get Content-Length
            file_size = 0
            async with httpx.AsyncClient(verify=False) as client:
                timeout = httpx.Timeout(10.0, connect=10.0)
                try:
                    head_resp = await client.head(
                        download_url, headers=headers, timeout=timeout
                    )
                    # Some servers might not return Content-Length on HEAD, try Range GET
                    # Also if Content-Length is suspiciously small (< 10MB), verify with Range
                    content_length = int(head_resp.headers.get("content-length", 0))

                    if (
                        "content-length" not in head_resp.headers
                        or content_length < 10 * 1024 * 1024
                    ):
                        # Try getting first byte
                        h_range = headers.copy()
                        h_range["Range"] = "bytes=0-0"
                        get_resp = await client.get(
                            download_url, headers=h_range, timeout=timeout
                        )
                        if "content-range" in get_resp.headers:
                            # Content-Range: bytes 0-0/123456
                            file_size = int(
                                get_resp.headers["content-range"].split("/")[-1]
                            )
                            # If Range returns a valid larger size, use it
                        elif content_length > 0:
                            file_size = content_length
                    else:
                        file_size = content_length
                except Exception as e:
                    # Fallback to simple download if size unknown
                    custom_print(f"获取文件大小失败: {e}", error_msg=True)
                    pass

            # Calculate thread count
            block_size_bytes = block_size * 1024 * 1024
            thread_count = 1
            if file_size > 0:
                 thread_count = int(file_size / block_size_bytes)
            
            custom_print(
                f"文件: {os.path.basename(save_path)}, 大小: {file_size / 1024 / 1024:.2f} MB, 块大小: {block_size} MB, 线程数: {thread_count}"
            )

            # Setup Progress Bar
            tqdm_kwargs = {
                "unit": "B",
                "unit_scale": True,
                "desc": os.path.basename(save_path),
                "ncols": 80,  # Fixed width to prevent staircase effect
                "ascii": True,  # Use ASCII characters for better compatibility
                "leave": False,
                "total": file_size if file_size > 0 else None,
                "mininterval": 1.0,  # Update max once per second to reduce spam
                "file": sys.stdout,  # Use stdout instead of stderr
            }
            # Remove position to avoid cursor issues in incompatible terminals
            # if position is not None:
            #    tqdm_kwargs["position"] = position

            pbar = tqdm(**tqdm_kwargs)

            # 2. Decide Strategy
            # If file_size < block_size, use single thread
            if file_size < block_size_bytes:
                async with httpx.AsyncClient(verify=False) as client:
                    timeout = httpx.Timeout(60.0, connect=60.0)
                    async with client.stream(
                        "GET", download_url, headers=headers, timeout=timeout
                    ) as response:
                        with open(save_path, "wb") as f:
                            async for chunk in response.aiter_bytes():
                                f.write(chunk)
                                pbar.update(len(chunk))
            else:
                # 3. Multi-part Download
                # Create placeholder file
                with open(save_path, "wb") as f:
                    f.truncate(file_size)

                part_size = file_size // thread_count
                tasks = []
                pbar_lock = asyncio.Lock()  # Lock for pbar updates
                for i in range(thread_count):
                    start = i * part_size
                    if i == thread_count - 1:
                        end = file_size - 1
                    else:
                        end = (i + 1) * part_size - 1

                    task = asyncio.create_task(
                        QuarkPanFileManager.download_part(
                            download_url,
                            headers,
                            start,
                            end,
                            save_path,
                            pbar,
                            pbar_lock=pbar_lock,
                        )
                    )
                    tasks.append(task)

                await asyncio.gather(*tasks)

            if position is not None:
                tqdm.write(f"下载完成: {os.path.basename(save_path)}")

        except Exception as e:
            tqdm.write(f"下载失败 {os.path.basename(save_path)}: {e}")
            # Clean up failed file? Maybe not, allow resume later?
            # os.remove(save_path)
            raise e
        finally:
            if pbar:
                pbar.close()
            if position is not None and position_queue:
                position_queue.put_nowait(position)
            if semaphore:
                semaphore.release()

    async def quark_file_download(
        self, fids: list[str], folder: str = "", folders_map=None
    ) -> None:
        folders_map = folders_map or {}
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "sys": "win32",
            "ve": "2.5.56",
            "ut": "",
            "guid": "",
        }

        data = {"fids": fids}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "accept-language": "zh-CN",
            "origin": "https://pan.quark.cn",
            "referer": "https://pan.quark.cn/",
            "cookie": self.cookies,
        }

        download_api = "https://drive-pc.quark.cn/1/clouddrive/file/download"
        # Known APIs verified through development:
        # - Create Directory: POST https://drive-pc.quark.cn/1/clouddrive/file
        # - Delete File/Dir: POST https://drive-pc.quark.cn/1/clouddrive/file/delete
        # - Get Share Token: POST https://drive-pc.quark.cn/1/clouddrive/share/sharepage/token
        # - Get Share Detail: GET https://drive-pc.quark.cn/1/clouddrive/share/sharepage/detail
        # - Get File List: GET https://drive-pc.quark.cn/1/clouddrive/file/sort
        # - User Info: GET https://pan.quark.cn/account/info
        # - Create Share: POST https://drive-pc.quark.cn/1/clouddrive/share
        # - File Rename: POST https://drive-pc.quark.cn/1/clouddrive/file/rename

        # Inferred/Experimental APIs:
        # - Cancel Share: POST https://drive-pc.quark.cn/1/clouddrive/share/delete (Inferred from file/delete pattern)

        for _ in range(2):
            async with httpx.AsyncClient(verify=False) as client:
                timeout = httpx.Timeout(60.0, connect=60.0)
                response = await client.post(
                    download_api,
                    json=data,
                    headers=headers,
                    params=params,
                    timeout=timeout,
                )
                json_data = response.json()

                if json_data.get("code") == 23018:
                    headers["User-Agent"] = (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) quark-cloud-drive/2.5.56 Chrome/100.0.4896.160 "
                        "Electron/18.3.5.12-a038f7b798 Safari/537.36 Channel/pckk_other_ch"
                    )
                    continue

                data_list = json_data.get("data", None)
                if json_data["status"] != 200:
                    custom_print(
                        f"文件下载地址列表获取失败, {json_data['message']}",
                        error_msg=True,
                    )
                    return
                elif data_list:
                    custom_print("文件下载地址列表获取成功")

                    save_folder = self.save_folder
                os.makedirs(save_folder, exist_ok=True)
                n = 0

                # Limit concurrent files to 3 to avoid overwhelming the system/display
                MAX_CONCURRENT_FILES = self.concurrent_files
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_FILES)
                position_queue = asyncio.Queue()
                for i in range(MAX_CONCURRENT_FILES):
                    position_queue.put_nowait(i)

                tasks = []
                custom_print(
                    f"开始批量下载 {len(data_list)} 个文件，同时下载数: {MAX_CONCURRENT_FILES}，单文件块大小: {self.block_size}MB"
                )

                for i in data_list:
                    n += 1
                    filename = i["file_name"]
                    # custom_print(f'开始下载第{n}个文件-{filename}')

                    # build save path start
                    base_path = ""
                    if "pdir_fid" in i:
                        pdir_fid = i["pdir_fid"]
                        while pdir_fid in folders_map:
                            base_path = (
                                "/" + folders_map[pdir_fid]["file_name"] + base_path
                            )
                            pdir_fid = folders_map[pdir_fid]["pdir_fid"]
                    final_save_folder = f"{save_folder}/{base_path}"
                    os.makedirs(final_save_folder, exist_ok=True)
                    # build save path stop

                    download_url = i["download_url"]
                    save_path = os.path.join(final_save_folder, filename)
                    headers = {
                        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, "
                        "like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0",
                        "origin": "https://pan.quark.cn",
                        "referer": "https://pan.quark.cn/",
                        "cookie": self.cookies,
                    }
                    task = asyncio.create_task(
                        self.download_file(
                            download_url,
                            save_path,
                            headers,
                            block_size=self.block_size,
                            semaphore=semaphore,
                            position_queue=position_queue,
                        )
                    )
                    tasks.append(task)

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            return

    async def submit_task(self, task_id: str, retry: int = 50) -> bool | dict:

        for i in range(retry):
            await asyncio.sleep(random.randint(500, 1000) / 1000)
            custom_print(f"第{i + 1}次提交任务")
            submit_url = (
                f"https://drive-pc.quark.cn/1/clouddrive/task?pr=ucpro&fr=pc&uc_param_str=&task_id={task_id}"
                f"&retry_index={i}&__dt=21192&__t={get_timestamp(13)}"
            )

            async with httpx.AsyncClient(verify=False) as client:
                timeout = httpx.Timeout(60.0, connect=60.0)
                response = await client.get(
                    submit_url, headers=self.headers, timeout=timeout
                )
                json_data = response.json()

            if json_data["message"] == "ok":
                if json_data["data"]["status"] == 2:
                    custom_print(f"DEBUG: submit_task response: {json_data}")
                    if "to_pdir_name" in json_data["data"]["save_as"]:
                        folder_name = json_data["data"]["save_as"]["to_pdir_name"]
                    else:
                        folder_name = " 根目录"
                    if json_data["data"]["task_title"] == "分享-转存":
                        custom_print(f"结束任务ID：{task_id}")
                        custom_print(f"文件保存位置：{folder_name} 文件夹")
                    return json_data
            else:
                if (
                    json_data["code"] == 32003
                    and "capacity limit" in json_data["message"]
                ):
                    custom_print(
                        "转存失败，网盘容量不足！请注意当前已成功保存的个数，避免重复保存",
                        error_msg=True,
                    )
                elif json_data["code"] == 41013:
                    custom_print(
                        f"”{to_dir_name}“ 网盘文件夹不存在，请重新运行按3切换保存目录后重试！",
                        error_msg=True,
                    )
                else:
                    custom_print(f"错误信息：{json_data['message']}", error_msg=True)
                input(f"[{get_datetime()}] 已退出程序")
                sys.exit()

    async def one_click_download_pipeline(self, share_url: str) -> None:
        # Check if the share link belongs to the current user
        try:
            pwd_id = self.get_pwd_id(share_url).split("#")[0]
            match_password = re.search("pwd=(.*?)(?=$|&)", share_url)
            password = match_password.group(1) if match_password else ""
            stoken = await self.get_stoken(pwd_id, password)
            if stoken:
                is_owner, _ = await self.get_detail(pwd_id, stoken)
                if is_owner == 1:
                    custom_print(
                        "检测到该分享链接由当前用户创建，无需转存，直接开始下载。"
                    )
                    await self.run(share_url, self.pdir_id, download=True)
                    return
        except Exception as e:
            custom_print(
                f"检查链接所有权时出错: {e}，将尝试继续执行常规流程。", error_msg=True
            )

        temp_dir_fid = None
        created_shares = []

        # Use a random temp directory name to avoid "Content Violation" flags
        self.TEMP_DIR_NAME = f"_Download_{generate_random_code()}"
        custom_print(f"=== 步骤0: 准备临时目录 {self.TEMP_DIR_NAME} ===")

        # 0. Check and create temp dir (search for any old temp dirs and clean if possible, but focus on new one)
        # We won't aggressively delete old ones here to avoid deleting user data by mistake,
        # but using a unique name prevents conflicts.

        # Create temp dir WITHOUT updating global config to preserve Option 1 settings
        temp_dir_fid = await self.create_dir(self.TEMP_DIR_NAME, update_config=False)

        if not temp_dir_fid or temp_dir_fid == "0":
            custom_print(
                f"创建临时目录 {self.TEMP_DIR_NAME} 失败，无法继续。", error_msg=True
            )
            sys.exit(102)  # Exit code 102: Temp Dir Creation Failed

        try:
            custom_print("=== 步骤1: 分享地址转存文件 ===")
            # Step 1: Save
            # We explicitly use temp_dir_fid for saving, ignoring self.pdir_id
            saved_fid = await self.run(share_url, temp_dir_fid, download=False)

            # Check if save was successful. run() returns fid on success, None on failure.
            # However, run() implementation needs to be checked if it returns None on failure.
            # Assuming run() handles its own error printing, but we need to catch the failure here.
            if not saved_fid:
                custom_print("文件转存失败，终止流程。", error_msg=True)
                sys.exit(103)  # Exit code 103: Save Failed

            target_fid = saved_fid if saved_fid else temp_dir_fid

            custom_print("\n=== 步骤2: 批量生成分享链接 ===")
            # Step 2: Share
            max_retries = 3
            share_success = False
            for i in range(max_retries):
                try:
                    shares = await self.share_run(
                        share_url="",
                        folder_id=target_fid,
                        fid=target_fid,
                        url_type=1,
                        expired_type=2,
                        traverse_depth=0,
                    )
                    if shares:
                        created_shares.extend(shares)
                        share_success = True
                        break
                    else:
                        raise Exception("生成的分享ID列表为空")
                except Exception as e:
                    custom_print(
                        f"分享失败 (尝试 {i+1}/{max_retries}): {e}", error_msg=True
                    )
                    if i < max_retries - 1:
                        wait_time = 2 * (i + 1)
                        custom_print(f"等待 {wait_time} 秒后重试...")
                        await asyncio.sleep(wait_time)
                    else:
                        custom_print("多次尝试分享失败，跳过。", error_msg=True)

            if not share_success:
                custom_print("无法生成有效的分享链接，终止下载流程。", error_msg=True)
                sys.exit(104)  # Exit code 104: Share Creation Failed

            custom_print("\n=== 步骤3: 下载到本地 ===")
            # Step 3: Download
            try:
                urls = load_url_file("output/share_url.txt")
                if not urls:
                    custom_print("未找到生成的分享链接，跳过下载步骤。", error_msg=True)
                    sys.exit(105)  # Exit code 105: No Download URLs
                else:
                    custom_print(f"检测到 {len(urls)} 个分享链接，开始下载...")
                    for index, url in enumerate(urls):
                        custom_print(f"正在处理第 {index + 1} 个链接: {url}")
                        # For downloading, the save path structure is handled internally,
                        # but passing temp_dir_fid keeps context if needed
                        # Note: run(download=True) relies on quark_file_download which might raise exceptions
                        await self.run(url.strip(), temp_dir_fid, download=True)

            except FileNotFoundError:
                custom_print(
                    "output/share_url.txt 文件未找到，无法下载。", error_msg=True
                )
                sys.exit(105)
            except Exception as e:
                custom_print(f"下载过程中发生错误: {e}", error_msg=True)
                sys.exit(106)  # Exit code 106: Download Failed

        finally:
            cleanup_error = False

            # 4.1 Cancel Shares
            if created_shares:
                custom_print(
                    f"\n=== 步骤4.1: 取消创建的 {len(created_shares)} 个分享链接 ==="
                )
                for share_id in created_shares:
                    if not await self.cancel_share(share_id):
                        custom_print(
                            f"错误: 分享ID {share_id} 取消失败，可能导致下次运行重复下载。",
                            error_msg=True,
                        )
                        cleanup_error = True

            # 4.2 Delete Temp Dir
            custom_print(f"\n=== 步骤4.2: 清理临时目录 {self.TEMP_DIR_NAME} ===")
            if temp_dir_fid and temp_dir_fid != "0":
                if not await self.delete_file(temp_dir_fid):
                    custom_print(
                        f"错误: 临时目录 {self.TEMP_DIR_NAME} 删除失败，可能影响下次运行。",
                        error_msg=True,
                    )
                    cleanup_error = True

            if cleanup_error:
                custom_print("清理环节发生错误，请检查日志并手动处理。", error_msg=True)
                sys.exit(107)  # Exit code 107: Cleanup Failed

    def parse_size(self, size_str: Union[str, int]) -> int:
        """Parse size string with units (MB, GB) to MB integer."""
        if isinstance(size_str, int):
            return size_str
        
        size_str = size_str.upper().strip()
        match = re.match(r"^(\d+)\s*(MB|GB)?$", size_str)
        if not match:
            # Default to MB if just a number string
            try:
                return int(size_str)
            except ValueError:
                return 100
        
        value = int(match.group(1))
        unit = match.group(2)
        
        if unit == "GB":
            return value * 1024
        return value

    def init_config(self, _user, _pdir_id, _dir_name):
        try:
            os.makedirs("output", exist_ok=True)
            
            # 1. Handle Config (Static Settings)
            try:
                config_data = read_config(f"{CONFIG_DIR}/config.json", "json")
            except (json.decoder.JSONDecodeError, FileNotFoundError):
                config_data = {}
            
            # Default block size 100MB
            # Parse block_size from config which might be string with unit
            raw_block_size = config_data.get("block_size", 100)
            self.block_size = self.parse_size(raw_block_size)
            self.concurrent_files = config_data.get("concurrent_files", 3)

            # Update config file if new parameters are missing or need cleanup
            updated_config = False
            if "thread_count" in config_data:
                del config_data["thread_count"]
                updated_config = True
            if "block_size" not in config_data:
                config_data["block_size"] = "100MB"
                updated_config = True
            if "multipart_threshold" in config_data:
                del config_data["multipart_threshold"]
                updated_config = True
            if "concurrent_files" not in config_data:
                config_data["concurrent_files"] = self.concurrent_files
                updated_config = True
            
            # Remove legacy state fields from config if present
            for field in ["user", "pdir_id", "dir_name"]:
                if field in config_data:
                    del config_data[field]
                    updated_config = True

            if updated_config:
                save_config(
                    f"{CONFIG_DIR}/config.json",
                    content=json.dumps(config_data, ensure_ascii=False),
                )

            # 2. Handle State (Dynamic User Data)
            try:
                state_data = read_config("output/state.json", "json")
            except (json.decoder.JSONDecodeError, FileNotFoundError):
                state_data = {}

            saved_user = state_data.get("user", "jack")
            
            if saved_user != _user:
                # User changed, reset state
                _pdir_id = "0"
                _dir_name = "根目录"
                new_state = {
                    "user": _user,
                    "pdir_id": _pdir_id,
                    "dir_name": _dir_name,
                }
                save_config(
                    "output/state.json",
                    content=json.dumps(new_state, ensure_ascii=False),
                )
            else:
                # User same, load state
                _pdir_id = state_data.get("pdir_id", "0")
                _dir_name = state_data.get("dir_name", "根目录")
                
                # Ensure state file exists and has correct data
                if not state_data or "user" not in state_data:
                     new_state = {
                        "user": _user,
                        "pdir_id": _pdir_id,
                        "dir_name": _dir_name,
                    }
                     save_config(
                        "output/state.json",
                        content=json.dumps(new_state, ensure_ascii=False),
                    )

        except Exception as e:
            custom_print(f"初始化配置出错: {e}", error_msg=True)
            # Fallback defaults
            self.block_size = 100
            self.concurrent_files = 3
            
        return _user, _pdir_id, _dir_name

    async def load_folder_id(self, renew=False) -> Union[tuple, None]:

        self.user = await self.get_user_info()
        self.user, self.pdir_id, self.dir_name = self.init_config(
            self.user, self.pdir_id, self.dir_name
        )
        if not renew:
            custom_print(f"用户名：{self.user}")
            custom_print(f"你当前选择的网盘保存目录: {self.dir_name} 文件夹")

        if renew:
            pdir_id = input(f"[{get_datetime()}] 请输入保存位置的文件夹ID(可为空): ")
            if pdir_id == "0":
                self.dir_name = "根目录"
                new_state = {
                    "user": self.user,
                    "pdir_id": self.pdir_id,
                    "dir_name": self.dir_name,
                }
                save_config(
                    "output/state.json",
                    content=json.dumps(new_state, ensure_ascii=False),
                )

            elif len(pdir_id) < 32:
                file_list_data = await self.get_sorted_file_list(
                    sort="file_type:asc,file_name:asc"
                )
                fd_list = file_list_data["data"]["list"]
                fd_list = [{i["fid"]: i["file_name"]} for i in fd_list if i.get("dir")]
                if fd_list:
                    table = PrettyTable(["序号", "文件夹ID", "文件夹名称"])
                    for idx, item in enumerate(fd_list, 1):
                        key, value = next(iter(item.items()))
                        table.add_row([idx, key, value])
                    print(table)
                    num = input(
                        f"[{get_datetime()}] 请选择你要保存的位置（输入对应序号）: "
                    )
                    if not num or int(num) > len(fd_list):
                        custom_print("输入序号不存在，保存目录切换失败", error_msg=True)
                        state_data = read_config("output/state.json", "json")
                        return state_data.get("pdir_id", "0"), state_data.get("dir_name", "根目录")

                    item = fd_list[int(num) - 1]
                    self.pdir_id, self.dir_name = next(iter(item.items()))
                    new_state = {
                        "user": self.user,
                        "pdir_id": self.pdir_id,
                        "dir_name": self.dir_name,
                    }
                    save_config(
                        "output/state.json",
                        content=json.dumps(new_state, ensure_ascii=False),
                    )

        return self.pdir_id, self.dir_name

    async def get_share_task_id(
        self,
        fid: str,
        file_name: str,
        url_type: int = 1,
        expired_type: int = 2,
        password: str = "",
    ) -> str:

        json_data = {
            "fid_list": [fid],
            "title": file_name,
            "url_type": url_type,
            "expired_type": expired_type,
        }
        if url_type == 2:
            if password:
                json_data["passcode"] = password
            else:
                json_data["passcode"] = generate_random_code()

        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
        }

        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.post(
                "https://drive-pc.quark.cn/1/clouddrive/share",
                params=params,
                json=json_data,
                headers=self.headers,
                timeout=timeout,
            )
            json_data = response.json()
            if json_data.get("status") != 200 or not json_data.get("data"):
                custom_print(f"创建分享任务失败: {json_data}", error_msg=True)
                raise Exception(f"Create share task failed: {json_data.get('message')}")
            return json_data["data"]["task_id"]

    async def get_share_id(self, task_id: str) -> str:
        for i in range(20):  # Retry loop for async task completion
            params = {
                "pr": "ucpro",
                "fr": "pc",
                "uc_param_str": "",
                "task_id": task_id,
                "retry_index": str(i),
            }
            async with httpx.AsyncClient(verify=False) as client:
                timeout = httpx.Timeout(60.0, connect=60.0)
                response = await client.get(
                    "https://drive-pc.quark.cn/1/clouddrive/task",
                    params=params,
                    headers=self.headers,
                    timeout=timeout,
                )
                json_data = response.json()
                data = json_data.get("data", {})

                if not data:
                    await asyncio.sleep(1)
                    continue

                # Status 2 seems to be success for tasks
                if "share_id" in data:
                    return data["share_id"]

                status = data.get("status")
                if status == 2:
                    # Should have share_id, but if not, maybe next poll?
                    pass
                elif status == 0:
                    # Pending/Running
                    await asyncio.sleep(1)
                    continue
                else:
                    # Failure status
                    custom_print(
                        f"获取share_id失败 (Task Status {status}): {json_data}",
                        error_msg=True,
                    )
                    raise Exception(f"Share task failed with status {status}")

        custom_print(f"获取share_id超时: {json_data}", error_msg=True)
        raise Exception("Timeout waiting for share_id")

    async def submit_share(self, share_id: str) -> tuple:
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
        }

        json_data = {
            "share_id": share_id,
        }
        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.post(
                "https://drive-pc.quark.cn/1/clouddrive/share/password",
                params=params,
                json=json_data,
                headers=self.headers,
                timeout=timeout,
            )
            json_data = response.json()
            share_url = json_data["data"]["share_url"]
            title = json_data["data"]["title"]
            if "passcode" in json_data["data"]:
                share_url = share_url + f"?pwd={json_data['data']['passcode']}"
            return share_url, title

    async def cancel_share(self, share_id: str) -> bool:
        # Note: The 'delete' API endpoint is inferred from standard RESTful patterns and similar drive APIs.
        # If this endpoint is incorrect, it may need adjustment based on actual network traffic analysis from the Quark web client.
        # Common variations include /share/cancel, /share/remove, or passing share_id in the body or query params differently.
        api = "https://drive-pc.quark.cn/1/clouddrive/share/delete"
        params = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
        }
        data = {"share_ids": [share_id]}
        async with httpx.AsyncClient(verify=False) as client:
            timeout = httpx.Timeout(60.0, connect=60.0)
            response = await client.post(
                api, json=data, params=params, headers=self.headers, timeout=timeout
            )
            # Add robust error handling since this API is experimental
            try:
                json_data = response.json()
                if json_data.get("code") == 0:
                    custom_print(f"分享链接 (ShareID: {share_id}) 取消成功")
                    return True
                else:
                    custom_print(
                        f"取消分享失败 (API返回错误): {json_data}",
                        error_msg=True,
                    )
                    return False
            except Exception as e:
                custom_print(f"取消分享请求异常: {e}", error_msg=True)
                return False

    async def share_run(
        self,
        share_url: str,
        folder_id: Union[str, None] = None,
        url_type: int = 1,
        expired_type: int = 2,
        password: str = "",
        traverse_depth: int = 2,
        fid: str = None,
    ) -> list[str]:
        first_dir = ""
        second_dir = ""
        created_share_ids = []
        try:
            self.folder_id = folder_id
            if fid:
                pwd_id = fid
                custom_print(f"正在分享文件夹ID：{pwd_id}")
            else:
                custom_print(f"文件夹网页地址：{share_url}")
                pwd_id = share_url.rsplit("/", maxsplit=1)[1].split("-")[0]

            first_page = 1
            n = 0
            error = 0
            os.makedirs("output", exist_ok=True)
            save_share_path = "output/share_url.txt"

            safe_copy(save_share_path, "output/share_url_backup.txt")
            with open(save_share_path, "w", encoding="utf-8"):
                pass

            # 如果遍历深度为0，直接分享根目录
            if traverse_depth == 0:
                try:
                    share_name = "转存文件夹" if fid and fid != "0" else "根目录"
                    custom_print(f"开始分享: {share_name}")
                    task_id = await self.get_share_task_id(
                        pwd_id,
                        share_name,
                        url_type=url_type,
                        expired_type=expired_type,
                        password=password,
                    )
                    share_id = await self.get_share_id(task_id)
                    share_url, title = await self.submit_share(share_id)
                    created_share_ids.append(share_id)
                    with open(save_share_path, "a", encoding="utf-8") as f:
                        content = f"1 | {title} | {share_url}"
                        f.write(content + "\n")
                        custom_print(f"分享 {title} 成功")
                    return created_share_ids
                except Exception as e:
                    print("分享失败：", e)
                    return created_share_ids

            while True:
                json_data = await self.get_sorted_file_list(
                    pwd_id,
                    page=str(first_page),
                    size="50",
                    fetch_total="1",
                    sort="file_type:asc,file_name:asc",
                )
                for i1 in json_data["data"]["list"]:
                    if i1["dir"]:
                        first_dir = i1["file_name"]
                        # 如果遍历深度为1，直接分享一级目录
                        if traverse_depth == 1:
                            n += 1
                            share_success = False
                            share_error_msg = ""
                            fid = ""
                            for i in range(3):
                                try:
                                    custom_print(f"{n}.开始分享 {first_dir} 文件夹")
                                    random_time = random.choice([0.5, 1, 1.5, 2])
                                    await asyncio.sleep(random_time)
                                    fid = i1["fid"]
                                    task_id = await self.get_share_task_id(
                                        fid,
                                        first_dir,
                                        url_type=url_type,
                                        expired_type=expired_type,
                                        password=password,
                                    )
                                    share_id = await self.get_share_id(task_id)
                                    share_url, title = await self.submit_share(share_id)
                                    created_share_ids.append(share_id)
                                    with open(
                                        save_share_path, "a", encoding="utf-8"
                                    ) as f:
                                        content = f"{n} | {first_dir} | {share_url}"
                                        f.write(content + "\n")
                                        custom_print(f"{n}.分享成功 {first_dir} 文件夹")
                                        share_success = True
                                        break
                                except Exception as e:
                                    share_error_msg = e
                                    error += 1

                            if not share_success:
                                print("分享失败：", share_error_msg)
                                save_config(
                                    "output/share_error.txt",
                                    content=f"{error}.{first_dir} 文件夹\n",
                                    mode="a",
                                )
                                save_config(
                                    "output/retry.txt",
                                    content=f"{n} | {first_dir} | {fid}\n",
                                    mode="a",
                                )
                            continue

                        # 遍历深度为2，遍历二级目录
                        second_page = 1
                        while True:
                            # print(f'正在获取{first_dir}第{first_page}页，二级目录第{second_page}页，目前共分享{n}文件')
                            json_data2 = await self.get_sorted_file_list(
                                i1["fid"],
                                page=str(second_page),
                                size="50",
                                fetch_total="1",
                                sort="file_type:asc,file_name:asc",
                            )
                            for i2 in json_data2["data"]["list"]:
                                if i2["dir"]:
                                    n += 1
                                    share_success = False
                                    share_error_msg = ""
                                    fid = ""
                                    for i in range(3):
                                        try:
                                            second_dir = i2["file_name"]
                                            custom_print(
                                                f"{n}.开始分享 {first_dir}/{second_dir} 文件夹"
                                            )
                                            random_time = random.choice(
                                                [0.5, 1, 1.5, 2]
                                            )
                                            await asyncio.sleep(random_time)
                                            # print('获取到文件夹ID：', i2['fid'])
                                            fid = i2["fid"]
                                            task_id = await self.get_share_task_id(
                                                fid,
                                                second_dir,
                                                url_type=url_type,
                                                expired_type=expired_type,
                                                password=password,
                                            )
                                            share_id = await self.get_share_id(task_id)
                                            share_url, title = await self.submit_share(
                                                share_id
                                            )
                                            created_share_ids.append(share_id)
                                            with open(
                                                save_share_path, "a", encoding="utf-8"
                                            ) as f:
                                                content = f"{n} | {first_dir} | {second_dir} | {share_url}"
                                                f.write(content + "\n")
                                                custom_print(
                                                    f"{n}.分享成功 {first_dir}/{second_dir} 文件夹"
                                                )
                                                share_success = True
                                                break

                                        except Exception as e:
                                            share_error_msg = e
                                            error += 1

                                    if not share_success:
                                        print("分享失败：", share_error_msg)
                                        save_config(
                                            "output/share_error.txt",
                                            content=f"{error}.{first_dir}/{second_dir} 文件夹\n",
                                            mode="a",
                                        )
                                        save_config(
                                            "output/retry.txt",
                                            content=f"{n} | {first_dir} | {second_dir} | {fid}\n",
                                            mode="a",
                                        )
                            second_total = json_data2["metadata"]["_total"]
                            second_size = json_data2["metadata"]["_size"]
                            second_page = json_data2["metadata"]["_page"]
                            if second_size * second_page >= second_total:
                                break
                            second_page += 1

                second_total = json_data["metadata"]["_total"]
                second_size = json_data["metadata"]["_size"]
                second_page = json_data["metadata"]["_page"]
                if second_size * second_page >= second_total:
                    break
                first_page += 1
            custom_print(f"总共分享了 {n} 个文件夹，已经保存至 {save_share_path}")
            return created_share_ids

        except Exception as e:
            print("分享失败：", e)
            with open("output/share_error.txt", "a", encoding="utf-8") as f:
                f.write(f"{first_dir}/{second_dir} 文件夹")
            return created_share_ids

    async def share_run_retry(
        self,
        retry_url: str,
        url_type: int = 1,
        expired_type: int = 2,
        password: str = "",
    ):

        data_list = retry_url.split("\n")
        n = 0
        error = 0
        save_share_path = "output/retry_share_url.txt"
        error_data = []
        for i1 in data_list:
            data = i1.split(" | ")
            if data and len(data) == 4:
                first_dir = data[-3]
                second_dir = data[-2]
                fid = data[-1]
                share_error_msg = ""
                for i in range(3):
                    try:
                        task_id = await self.get_share_task_id(
                            fid,
                            second_dir,
                            url_type=url_type,
                            expired_type=expired_type,
                            password=password,
                        )
                        share_id = await self.get_share_id(task_id)
                        share_url, title = await self.submit_share(share_id)
                        with open(save_share_path, "a", encoding="utf-8") as f:
                            content = f"{n} | {first_dir} | {second_dir} | {share_url}"
                            f.write(content + "\n")
                            custom_print(
                                f"{n}.分享成功 {first_dir}/{second_dir} 文件夹"
                            )
                            share_success = True
                            break
                    except Exception as e:
                        share_error_msg = e
                        error += 1

                if not share_success:
                    print("分享失败：", share_error_msg)
                    error_data.append(i1)
        error_content = "\n".join(error_data)
        save_config(path="output/retry.txt", content=error_content, mode="w")


def clean_share_dir():
    share_dir = "output"
    if os.path.exists(share_dir):
        for filename in os.listdir(share_dir):
            file_path = os.path.join(share_dir, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                custom_print(
                    f"Failed to delete {file_path}. Reason: {e}", error_msg=True
                )
    else:
        os.makedirs(share_dir, exist_ok=True)


def load_url_file(fpath: str) -> list[str]:
    url_pattern = re.compile(r"https?://\S+")

    with open(fpath, encoding="utf-8") as f:
        content = f.read()

    return url_pattern.findall(content)


def print_ascii():
    print(
        r"""
║                                     _                                  _                     _       ║    
║       __ _   _   _    __ _   _ __  | | __    _ __     __ _   _ __     | |_    ___     ___   | |      ║
║      / _  | | | | |  / _  | | '__| | |/ /   | '_ \   / _  | |  _ \    | __|  / _ \   / _ \  | |      ║
║     | (_| | | |_| | | (_| | | |    |   <    | |_) | | (_| | | | | |   | |_  | (_) | | (_) | | |      ║
║      \__, |  \__,_|  \__,_| |_|    |_|\_\   | .__/   \__,_| |_| |_|    \__|  \___/   \___/  |_|      ║
║         |_|                                 |_|                                                      ║""".strip()
    )


def print_menu() -> None:
    print(
        "╔══════════════════════════════════════════════════════════════════════════════════════════════════════╗"
    )
    print_ascii()
    print(
        "║                                                                                                      ║"
    )
    print(
        "║                                  Author: Hmily  Version: 0.0.6                                       ║"
    )
    print(
        "║                          GitHub: https://github.com/ihmily/QuarkPanTool                              ║"
    )
    print(
        "╠══════════════════════════════════════════════════════════════════════════════════════════════════════╣"
    )
    print(
        "║     1.分享地址转存文件                                                                                  ║"
    )
    print(
        "║     2.批量生成分享链接                                                                                  ║"
    )
    print(
        "║     3.切换网盘保存目录                                                                                  ║"
    )
    print(
        "║     4.创建网盘文件夹                                                                                    ║"
    )
    print(
        "║     5.下载到本地                                                                                       ║"
    )
    print(
        "║     6.登录                                                                                            ║"
    )
    print(
        "║     7.一键下载他人分享链接(功能1+2+5)                                                                    ║"
    )
    print(
        "╚══════════════════════════════════════════════════════════════════════════════════════════════════════╝"
    )


if __name__ == "__main__":
    # CLI Argument Parsing
    parser = argparse.ArgumentParser(description="QuarkPanTool Automation")
    parser.add_argument("--download", help="Shared URL to download")
    parser.add_argument("--cookie", help="Cookie string to use")
    parser.add_argument("--path", help="Download directory to save files")
    args, unknown = parser.parse_known_args()

    if args.cookie:
        save_config(f"{CONFIG_DIR}/cookies.txt", args.cookie)

    quark_file_manager = QuarkPanFileManager(headless=False, slow_mo=500)
    if args.path and args.path.strip():
        quark_file_manager.save_folder = args.path.strip()
        try:
            os.makedirs(quark_file_manager.save_folder, exist_ok=True)
        except Exception:
            pass

    if args.download:
        # Automation Mode
        clean_share_dir()  # Clean share directory before running

        # Initialize user info first to populate self.user etc.
        user_name = asyncio.run(quark_file_manager.get_user_info())
        # We need to ensure config is loaded/initialized
        asyncio.run(quark_file_manager.load_folder_id())

        custom_print(f"自动化模式启动")
        custom_print(f"目标URL: {args.download}")

        asyncio.run(quark_file_manager.one_click_download_pipeline(args.download))
        sys.exit(0)

    while True:
        print_menu()

        to_dir_id, to_dir_name = asyncio.run(quark_file_manager.load_folder_id())

        input_text = input("请输入你的选择(1—7或q退出)：")

        if input_text and input_text.strip() in ["q", "Q"]:
            print("已退出程序！")
            sys.exit(0)

        if input_text and input_text.strip() in [str(i) for i in range(1, 8)]:
            if input_text.strip() == "1":
                save_option = input("是否批量转存(1是 2否)：")
                if save_option and save_option == "1":
                    try:
                        urls = load_url_file("config/url.txt")
                        if not urls:
                            custom_print(
                                "\n分享地址为空！请先在config/url.txt文件中输入分享地址(一行一个)"
                            )
                            continue

                        custom_print(
                            f"\r检测到config/url.txt文件中有{len(urls)}条分享链接"
                        )
                        ok = input("请你确认是否开始批量保存(确认请按2):")
                        if ok and ok.strip() == "2":
                            for index, url in enumerate(urls):
                                print(f"正在转存第{index + 1}个")
                                asyncio.run(
                                    quark_file_manager.run(url.strip(), to_dir_id)
                                )
                    except FileNotFoundError:
                        with open("config/url.txt", "w", encoding="utf-8"):
                            sys.exit(-1)
                else:
                    url = input("请输入夸克文件分享地址：")
                    if url and len(url.strip()) > 20:
                        asyncio.run(quark_file_manager.run(url.strip(), to_dir_id))

            elif input_text.strip() == "2":
                share_option = input("请输入你的选择(1分享 2重试分享)：")
                if share_option and share_option == "1":
                    url = input("请输入需要分享的文件夹网页端页面地址：")
                    if not url or len(url.strip()) < 20:
                        continue
                else:
                    try:
                        url = read_config(path="output/retry.txt", mode="r")
                        if not url:
                            print("\nretry.txt 为空！请检查文件")
                            continue
                    except FileNotFoundError:
                        save_config("output/retry.txt", content="")
                        print("\noutput/retry.txt 文件为空！")
                        continue

                expired_option = {"1": 2, "2": 3, "3": 4, "4": 1}
                print("1.1天  2.7天  3.30天  4.永久")
                select_option = input("请输入分享时长选项：")
                _expired_type = expired_option.get(select_option, 4)
                is_private = input("是否加密(1否/2是)：")
                url_encrypt = 2 if is_private == "2" else 1
                passcode = (
                    input("请输入你想设置的分享提取码(直接回车，可随机生成):")
                    if url_encrypt == 2
                    else ""
                )

                print("\n\r请选择遍历深度：")
                print("0.不遍历（只分享根目录-默认）")
                print("1.遍历只分享一级目录")
                print("2.遍历只分享两级目录\n")
                traverse_option = input("请输入选项(0/1/2)：")
                _traverse_depth = 0  # 默认只分享根目录
                if traverse_option in ["1", "2"]:
                    _traverse_depth = int(traverse_option)

                if share_option and share_option == "1":
                    asyncio.run(
                        quark_file_manager.share_run(
                            url.strip(),
                            folder_id=to_dir_id,
                            url_type=int(url_encrypt),
                            expired_type=int(_expired_type),
                            password=passcode,
                            traverse_depth=_traverse_depth,
                        )
                    )
                else:
                    asyncio.run(
                        quark_file_manager.share_run_retry(
                            url.strip(),
                            url_type=url_encrypt,
                            expired_type=_expired_type,
                            password=passcode,
                        )
                    )

            elif input_text.strip() == "3":
                to_dir_id, to_dir_name = asyncio.run(
                    quark_file_manager.load_folder_id(renew=True)
                )
                custom_print(f"已切换保存目录至网盘 {to_dir_name} 文件夹\n")

            elif input_text.strip() == "4":
                create_name = input("请输入需要创建的文件夹名称：")
                if create_name:
                    asyncio.run(quark_file_manager.create_dir(create_name.strip()))
                else:
                    custom_print("创建的文件夹名称不可为空！", error_msg=True)

            elif input_text.strip() == "5":
                try:
                    is_batch = input("输入你的选择(1单个地址下载，2批量下载):")
                    if is_batch:
                        if is_batch.strip() == "1":
                            url = input("请输入夸克文件分享地址：")
                            asyncio.run(
                                quark_file_manager.run(
                                    url.strip(), to_dir_id, download=True
                                )
                            )
                        elif is_batch.strip() == "2":
                            urls = load_url_file("config/url.txt")
                            if not urls:
                                print(
                                    "\n分享地址为空！请先在config/url.txt文件中输入分享地址(一行一个)"
                                )
                                continue

                            for index, url in enumerate(urls):
                                asyncio.run(
                                    quark_file_manager.run(
                                        url.strip(), to_dir_id, download=True
                                    )
                                )

                except FileNotFoundError:
                    with open("config/url.txt", "w", encoding="utf-8"):
                        sys.exit(-1)

            elif input_text.strip() == "6":
                save_config(f"{CONFIG_DIR}/cookies.txt", "")
                quark_file_manager = QuarkPanFileManager(headless=False, slow_mo=500)
                quark_file_manager.get_cookies()

            elif input_text.strip() == "7":
                url = input("请输入夸克文件分享地址：")
                if url and len(url.strip()) > 20:
                    asyncio.run(
                        quark_file_manager.one_click_download_pipeline(url.strip())
                    )
                else:
                    custom_print("输入的链接无效", error_msg=True)

        else:
            custom_print("输入无效，请重新输入")
