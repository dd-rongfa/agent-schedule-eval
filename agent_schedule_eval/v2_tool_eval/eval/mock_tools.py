"""
假工具模块
用途：记录 Agent 的工具调用，不产生真实副作用。
在自动化测试里把这些假工具注入给 Agent，
就能断言"调了什么工具、传了什么参数"，
而不用真的等定时任务触发。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    name: str
    params: dict[str, Any]


# 默认的预设任务列表（通用场景，喝水×2 + 开会）
DEFAULT_MOCK_TASKS = [
    {"task_id": "mock-1", "content": "喝水", "time": "09:00", "recurrence": "daily"},
    {"task_id": "mock-2", "content": "开会", "time": "14:00", "recurrence": None},
    {"task_id": "mock-3", "content": "喝水", "time": "15:00", "recurrence": "daily"},
]


class FakeScheduler:
    """记录所有调度类工具调用，供测试断言使用。

    支持按 case 注入不同的 mock 任务列表：
        scheduler = FakeScheduler()
        scheduler.set_mock_tasks([
            {"task_id": "t-1", "content": "吃药", "time": "09:00", "recurrence": "daily"},
        ])
    """

    def __init__(self, current_time: str = "2026-04-10 14:30") -> None:
        self.calls: list[ToolCall] = []
        self._current_time = current_time
        self._mock_tasks: list[dict] = list(DEFAULT_MOCK_TASKS)
        self._created_tasks: list[dict] = []  # 动态追踪创建的任务
        self._next_id = 100

    def reset(self) -> None:
        self.calls.clear()
        self._created_tasks.clear()
        self._next_id = 100

    def set_current_time(self, time_str: str) -> None:
        """设置模拟的当前时间（供 get_current_time 返回）。"""
        self._current_time = time_str

    def set_mock_tasks(self, tasks: list[dict]) -> None:
        """设置 list_schedules 返回的预设任务列表（按 case 定制）。"""
        self._mock_tasks = list(tasks)

    # ---------- 工具方法（模拟 Agent 可调用的工具） ----------

    def get_current_time(self, **kwargs: Any) -> dict:
        call = ToolCall(name="get_current_time", params=kwargs)
        self.calls.append(call)
        return {"status": "ok", "current_time": self._current_time}

    def create_schedule(self, content: str, delay_minutes: int | None = None,
                        time: str | None = None, date: str | None = None,
                        recurrence: str | None = None,
                        **kwargs: Any) -> dict:
        task_id = f"mock-{self._next_id}"
        self._next_id += 1
        call = ToolCall(name="create_schedule", params={
            "content": content,
            "delay_minutes": delay_minutes,
            "time": time,
            "date": date,
            "recurrence": recurrence,
            **kwargs,
        })
        self.calls.append(call)
        # 追踪到动态列表，后续 list_schedules 可以看到
        self._created_tasks.append({
            "task_id": task_id, "content": content,
            "time": time or f"+{delay_minutes}min",
            "recurrence": recurrence,
        })
        return {"status": "ok", "task_id": task_id}

    def cancel_schedule(self, task_id: str | None = None,
                        description: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="cancel_schedule", params={
            "task_id": task_id,
            "description": description,
            **kwargs,
        })
        self.calls.append(call)
        # 从动态列表和预设列表中移除
        if task_id:
            self._mock_tasks = [t for t in self._mock_tasks if t["task_id"] != task_id]
            self._created_tasks = [t for t in self._created_tasks if t["task_id"] != task_id]
        return {"status": "ok"}

    def create_recurring(self, content: str, interval_minutes: int | None = None,
                         total_count: int | None = None, recurrence: str | None = None,
                         days: list[str] | None = None, time: str | None = None,
                         **kwargs: Any) -> dict:
        task_id = f"mock-recurring-{self._next_id}"
        self._next_id += 1
        call = ToolCall(name="create_recurring", params={
            "content": content,
            "interval_minutes": interval_minutes,
            "total_count": total_count,
            "recurrence": recurrence,
            "days": days,
            "time": time,
            **kwargs,
        })
        self.calls.append(call)
        self._created_tasks.append({
            "task_id": task_id, "content": content,
            "time": time or "recurring",
            "recurrence": recurrence or "custom",
        })
        return {"status": "ok", "task_id": task_id}

    def list_schedules(self, date: str | None = None,
                       keyword: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="list_schedules", params={
            "date": date, "keyword": keyword, **kwargs,
        })
        self.calls.append(call)
        # 合并预设任务 + 动态创建的任务
        all_tasks = self._mock_tasks + self._created_tasks
        return {"status": "ok", "tasks": all_tasks}

    def update_schedule(self, task_id: str, status: str | None = None,
                        content: str | None = None, time: str | None = None,
                        **kwargs: Any) -> dict:
        """更新提醒状态或内容（如 triggered → completed）。"""
        call = ToolCall(name="update_schedule", params={
            "task_id": task_id, "status": status, "content": content,
            "time": time, **kwargs,
        })
        self.calls.append(call)
        # 更新 mock 数据中的状态
        for t in self._mock_tasks:
            if t["task_id"] == task_id:
                if status:
                    t["status"] = status
                if content:
                    t["content"] = content
                if time:
                    t["time"] = time
                return {"status": "ok", "task_id": task_id, "updated": True}
        return {"status": "error", "message": f"未找到任务 {task_id}"}

    # ---------- 帮助方法，方便测试里做断言 ----------

    def called_tools(self) -> list[str]:
        """返回调用过的工具名列表，顺序保留。"""
        return [c.name for c in self.calls]

    def last_call(self) -> ToolCall | None:
        return self.calls[-1] if self.calls else None

    def calls_for(self, tool_name: str) -> list[ToolCall]:
        return [c for c in self.calls if c.name == tool_name]


# ── 默认 mock 数据（新工具） ───────────────────────────

DEFAULT_MOCK_TODOS = [
    {"todo_id": "todo-1", "content": "买菜", "status": "pending", "due_date": None},
    {"todo_id": "todo-2", "content": "写周报", "status": "pending", "due_date": "2026-04-11"},
]

DEFAULT_MOCK_MEDIA = [
    {"media_id": "media-1", "title": "庆余年", "type": "tv",
     "current_episode": 5, "total_episodes": 46},
    {"media_id": "media-2", "title": "三体", "type": "tv",
     "current_episode": 12, "total_episodes": 30},
]

DEFAULT_MOCK_APPS = [
    {"app_id": "app-1", "name": "地图", "aliases": ["地盘", "导航"]},
    {"app_id": "app-2", "name": "抖音", "aliases": ["抖影", "短视频"]},
    {"app_id": "app-3", "name": "微信", "aliases": ["weixin"]},
    {"app_id": "app-4", "name": "备忘录", "aliases": ["笔记", "notes"]},
]


class FakeTodoManager:
    """记录待办事项相关工具调用。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._mock_todos: list[dict] = list(DEFAULT_MOCK_TODOS)
        self._next_id = 100

    def reset(self) -> None:
        self.calls.clear()
        self._next_id = 100

    def set_mock_todos(self, todos: list[dict]) -> None:
        self._mock_todos = list(todos)

    def create_todo(self, content: str, priority: str | None = None,
                    due_date: str | None = None, **kwargs: Any) -> dict:
        todo_id = f"todo-{self._next_id}"
        self._next_id += 1
        call = ToolCall(name="create_todo", params={
            "content": content, "priority": priority, "due_date": due_date, **kwargs,
        })
        self.calls.append(call)
        self._mock_todos.append({
            "todo_id": todo_id, "content": content,
            "status": "pending", "due_date": due_date, "priority": priority,
        })
        return {"status": "ok", "todo_id": todo_id}

    def complete_todo(self, todo_id: str | None = None,
                      description: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="complete_todo", params={
            "todo_id": todo_id, "description": description, **kwargs,
        })
        self.calls.append(call)
        if todo_id:
            for t in self._mock_todos:
                if t["todo_id"] == todo_id:
                    t["status"] = "completed"
        return {"status": "ok"}

    def list_todos(self, status: str | None = None,
                   keyword: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="list_todos", params={
            "status": status, "keyword": keyword, **kwargs,
        })
        self.calls.append(call)
        todos = self._mock_todos
        if status:
            todos = [t for t in todos if t["status"] == status]
        return {"status": "ok", "todos": todos}

    def delete_todo(self, todo_id: str | None = None,
                    description: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="delete_todo", params={
            "todo_id": todo_id, "description": description, **kwargs,
        })
        self.calls.append(call)
        if todo_id:
            self._mock_todos = [t for t in self._mock_todos if t["todo_id"] != todo_id]
        return {"status": "ok"}

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


class FakeMediaPlayer:
    """记录媒体播放相关工具调用。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._mock_media: list[dict] = list(DEFAULT_MOCK_MEDIA)
        self._playing: dict | None = None

    def reset(self) -> None:
        self.calls.clear()
        self._playing = None

    def set_mock_media(self, media: list[dict]) -> None:
        self._mock_media = list(media)

    def play_media(self, title: str | None = None, episode: int | None = None,
                   resume: bool | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="play_media", params={
            "title": title, "episode": episode, "resume": resume, **kwargs,
        })
        self.calls.append(call)
        matched = None
        for m in self._mock_media:
            if title and title in m["title"]:
                matched = m
                break
        if matched:
            ep = episode or (matched["current_episode"] + 1 if resume else 1)
            self._playing = {"title": matched["title"], "episode": ep}
            return {"status": "ok", "playing": matched["title"], "episode": ep}
        return {"status": "error", "message": f"未找到 '{title}'"}

    def pause_media(self, **kwargs: Any) -> dict:
        call = ToolCall(name="pause_media", params=kwargs)
        self.calls.append(call)
        self._playing = None
        return {"status": "ok"}

    def get_play_history(self, **kwargs: Any) -> dict:
        call = ToolCall(name="get_play_history", params=kwargs)
        self.calls.append(call)
        history = [
            {"title": m["title"], "last_episode": m["current_episode"],
             "total_episodes": m["total_episodes"]}
            for m in self._mock_media
        ]
        return {"status": "ok", "history": history}

    def list_media_library(self, keyword: str | None = None,
                           media_type: str | None = None, **kwargs: Any) -> dict:
        call = ToolCall(name="list_media_library", params={
            "keyword": keyword, "type": media_type, **kwargs,
        })
        self.calls.append(call)
        return {"status": "ok", "media": self._mock_media}

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


class FakeAppLauncher:
    """记录应用启动相关工具调用。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._mock_apps: list[dict] = list(DEFAULT_MOCK_APPS)

    def reset(self) -> None:
        self.calls.clear()

    def set_mock_apps(self, apps: list[dict]) -> None:
        self._mock_apps = list(apps)

    def open_app(self, app_name: str, **kwargs: Any) -> dict:
        call = ToolCall(name="open_app", params={"app_name": app_name, **kwargs})
        self.calls.append(call)
        for a in self._mock_apps:
            if app_name in a["name"] or any(app_name in alias for alias in a.get("aliases", [])):
                return {"status": "ok", "opened": a["name"]}
        return {"status": "ok", "opened": app_name}

    def list_apps(self, **kwargs: Any) -> dict:
        call = ToolCall(name="list_apps", params=kwargs)
        self.calls.append(call)
        return {"status": "ok", "apps": [a["name"] for a in self._mock_apps]}

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


class FakeBash:
    """记录 bash/命令行调用。模拟 agent_tools.py 中的 bash 工具。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def reset(self) -> None:
        self.calls.clear()

    def bash(self, command: str, **kwargs: Any) -> dict:
        call = ToolCall(name="bash", params={"command": command, **kwargs})
        self.calls.append(call)
        # 模拟常见命令的输出
        cmd_lower = command.lower()
        if "start" in cmd_lower:
            return {"status": "ok", "output": "(launched)"}
        if "dir" in cmd_lower or "ls" in cmd_lower:
            return {"status": "ok", "output": "file1.txt\nfile2.txt\nfolder1/"}
        return {"status": "ok", "output": "(no output)"}

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


class FakeProgramFinder:
    """记录 find_program 调用。模拟 agent_tools.py 中的程序查找工具。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._mock_programs: dict[str, str] = {
            "微信": "C:\\Program Files\\Tencent\\WeChat\\WeChat.exe",
            "weixin": "C:\\Program Files\\Tencent\\WeChat\\WeChat.exe",
            "wechat": "C:\\Program Files\\Tencent\\WeChat\\WeChat.exe",
            "抖音": "C:\\Program Files\\Douyin\\Douyin.exe",
            "douyin": "C:\\Program Files\\Douyin\\Douyin.exe",
            "地图": "C:\\Program Files\\Amap\\Amap.exe",
            "chrome": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        }

    def reset(self) -> None:
        self.calls.clear()

    def set_mock_programs(self, programs: dict[str, str]) -> None:
        self._mock_programs = dict(programs)

    def find_program(self, keyword: str, **kwargs: Any) -> dict:
        call = ToolCall(name="find_program", params={"keyword": keyword, **kwargs})
        self.calls.append(call)
        kw = keyword.lower()
        for name, path in self._mock_programs.items():
            if kw in name.lower():
                return {"status": "ok", "path": path}
        return {"status": "not_found", "message": f"未找到 '{keyword}'"}

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


class FakeWindowController:
    """记录窗口控制调用。模拟 agent_tools.py 中的 control_window 工具。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._mock_windows: list[str] = ["微信", "Google Chrome", "Visual Studio Code"]

    def reset(self) -> None:
        self.calls.clear()

    def set_mock_windows(self, windows: list[str]) -> None:
        self._mock_windows = list(windows)

    def control_window(self, action: str, window_title: str, **kwargs: Any) -> dict:
        call = ToolCall(name="control_window", params={
            "action": action, "window_title": window_title, **kwargs,
        })
        self.calls.append(call)
        matched = [w for w in self._mock_windows if window_title.lower() in w.lower()]
        if matched:
            return {"status": "ok", "action": action, "window": matched[0]}
        return {"status": "error", "message": f"未找到窗口 '{window_title}'"}

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


# ── 后台任务状态查询（链式推理场景） ───────────────────

DEFAULT_MOCK_RUNNING_TASKS: list[dict] = []


class FakeTaskMonitor:
    """记录后台任务状态查询调用。Mock 返回预设的进度数据，
    供模型做数值推理（如估算剩余时间并设提醒）。"""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []
        self._mock_running_tasks: list[dict] = list(DEFAULT_MOCK_RUNNING_TASKS)

    def reset(self) -> None:
        self.calls.clear()

    def set_mock_running_tasks(self, tasks: list[dict]) -> None:
        self._mock_running_tasks = list(tasks)

    def check_task_status(self, task_id: str | None = None, **kwargs: Any) -> dict:
        """查询后台任务状态。返回 progress/elapsed/log 等信息。"""
        call = ToolCall(name="check_task_status", params={
            "task_id": task_id, **kwargs,
        })
        self.calls.append(call)
        if task_id:
            for t in self._mock_running_tasks:
                if t["task_id"] == task_id:
                    return {"status": "ok", "task": t}
            return {"status": "error", "message": f"未找到任务 {task_id}"}
        # 无 task_id 则返回所有运行中的任务
        if not self._mock_running_tasks:
            return {"status": "ok", "tasks": [], "message": "当前没有正在运行的任务"}
        return {"status": "ok", "tasks": self._mock_running_tasks}

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]


class ToolDispatcher:
    """统一工具分发器：聚合多个 Fake 工具，作为 agent_loop 的 tool handler。

    用法：
        dispatcher = ToolDispatcher()
        dispatcher.set_mock_tasks([...])       # 日程 mock
        dispatcher.set_mock_todos([...])       # 待办 mock
        result = agent_loop(client, model, messages, TOOLS, dispatcher)
    """

    def __init__(self, current_time: str = "2026-04-10 14:30") -> None:
        self.scheduler = FakeScheduler(current_time=current_time)
        self.todo = FakeTodoManager()
        self.media = FakeMediaPlayer()
        self.app = FakeAppLauncher()
        self.bash_runner = FakeBash()
        self.program_finder = FakeProgramFinder()
        self.window_ctrl = FakeWindowController()
        self.task_monitor = FakeTaskMonitor()
        self._tools = [self.scheduler, self.todo, self.media, self.app,
                       self.bash_runner, self.program_finder, self.window_ctrl,
                       self.task_monitor]

    def reset(self) -> None:
        for t in self._tools:
            t.reset()

    # ---- 便捷 setter ----
    def set_current_time(self, time_str: str) -> None:
        self.scheduler.set_current_time(time_str)

    def set_mock_tasks(self, tasks: list[dict]) -> None:
        self.scheduler.set_mock_tasks(tasks)

    def set_mock_todos(self, todos: list[dict]) -> None:
        self.todo.set_mock_todos(todos)

    def set_mock_media(self, media: list[dict]) -> None:
        self.media.set_mock_media(media)

    def set_mock_apps(self, apps: list[dict]) -> None:
        self.app.set_mock_apps(apps)

    def set_mock_running_tasks(self, tasks: list[dict]) -> None:
        self.task_monitor.set_mock_running_tasks(tasks)

    # ---- 聚合查询 ----
    @property
    def calls(self) -> list[ToolCall]:
        all_calls: list[ToolCall] = []
        for t in self._tools:
            all_calls.extend(t.calls)
        return all_calls

    def called_tools(self) -> list[str]:
        return [c.name for c in self.calls]

    def last_call(self) -> ToolCall | None:
        # 向后兼容：返回 scheduler 的最后一次调用（用于 delay_minutes 断言）
        return self.scheduler.last_call()

    def calls_for(self, tool_name: str) -> list[ToolCall]:
        return [c for c in self.calls if c.name == tool_name]

    def __getattr__(self, name: str) -> Any:
        """分发未知属性到子工具（工具方法路由）。"""
        for tool in self._tools:
            fn = getattr(tool, name, None)
            if fn is not None and callable(fn):
                return fn
        raise AttributeError(f"No tool handler for '{name}'")
