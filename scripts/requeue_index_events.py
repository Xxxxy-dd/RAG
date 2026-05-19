"""把现有的 rag:index-events 流里的事件安全地重新入队到同一流，随后删除旧条目。

用途：当事件是在 worker 启动前写入的，vector worker 使用 XREADGROUP with '>' 可能无法读取这些旧事件。

注意：请在运行前确认 Redis_URL 环境变量或默认 redis://127.0.0.1:6379/0。脚本会打印处理统计。
"""

from __future__ import annotations

import os
import sys

try:
    import redis
except Exception:
    print("请先安装 redis: pip install redis")
    raise

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
STREAM_KEY = os.getenv("REDIS_INDEX_EVENTS_STREAM", "rag:index-events")
BATCH = 200


def connect():
    return redis.from_url(REDIS_URL)


def requeue_all(stream_key: str = STREAM_KEY, batch: int = BATCH) -> None:
    r = connect()
    total = 0
    to_delete: list[str] = []
    print(f"连接 {REDIS_URL}，流：{stream_key}")

    # 使用 XRANGE 获取所有现存消息的 ID
    start = b"-"
    end = b"+"
    # xrange 返回 [(id, {field: value, ...}), ...]
    items = r.xrange(stream_key, min=start, max=end)
    if not items:
        print("流为空：没有要重排的事件。")
        return

    print(f"发现 {len(items)} 条事件，开始重入队并删除原件（逐条处理以降低内存占用）...")
    for idx, (msg_id, fields) in enumerate(items, start=1):
        # 直接把同样的字段写回流，得到新 ID
        try:
            new_id = r.xadd(stream_key, fields)
            to_delete.append(msg_id)
            total += 1
            if total % 50 == 0:
                print(f"已重排 {total} 条，最新新ID={new_id}, 删除原件批量提交...")
                # 批量删除已累计的旧 id，避免列表无限增长
                r.xdel(stream_key, *to_delete)
                to_delete = []
        except Exception as exc:
            print(f"处理消息 {msg_id} 时出错: {exc}")

    # 删除剩余的旧 id
    if to_delete:
        r.xdel(stream_key, *to_delete)

    print(f"重排完成，总计重入队 {total} 条事件（原件已删除）。")


if __name__ == "__main__":
    try:
        requeue_all()
    except Exception as e:
        print("发生错误:", e)
        sys.exit(2)
