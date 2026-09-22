"""
@author:alex
@date:2024/10/30
@time:17:15
"""

__author__ = "alex"
import orjson
from sqlalchemy import Text, TypeDecorator
from sqlalchemy.orm import Mapper, RelationshipProperty

# noinspection PyPep8Naming


def get_relations(cls):
    if isinstance(cls, Mapper):
        mapper = cls
    else:
        mapper = cls.__mapper__
    return [c for c in mapper.attrs if isinstance(c, RelationshipProperty)]


def path_to_relations_list(cls, path):
    path_as_list = path.split(".")
    relations = get_relations(cls)
    relations_list = []
    for item in path_as_list:
        for rel in relations:
            if rel.key == item:
                relations_list.append(rel)
                relations = get_relations(rel.entity)
                break
    return relations_list


class JSONText(TypeDecorator):
    """
    自定义 TypeDecorator，用于将 TEXT 字段中的 JSON 数据自动转换为 Python 对象，
    兼容空字符串、None，以及存储 dict 或 list 数据的情况。
    """

    impl = Text
    cache_ok = True  # 添加这一行

    def process_bind_param(self, value, dialect):
        # 写入数据库前，将 Python 对象转换为 JSON 字符串
        # 如果 value 为 None，则返回空字符串以兼容已有数据默认值
        if value is None:
            return ""
        try:
            # orjson.dumps 返回 bytes，而这一列声明的 impl 是 Text。不解码就会把 bytes 交给
            # 驱动：SQLite 实测落成 blob（于是 `WHERE payload = '{"a":1}'` 这种和文本字面量
            # 比较的查询匹配不上），PostgreSQL 的 TEXT 列收到 bytes 会直接报错。
            return orjson.dumps(value).decode("utf-8")
        except (TypeError, ValueError):
            # orjson 不认识的对象（比如自定义类）原样交回，由调用方和驱动去决定。
            # 注意字符串走不到这里：orjson.dumps("hello") 成功，返回 b'"hello"'。
            return value

    def process_result_value(self, value, dialect):
        # 从数据库读取后，将字符串解析为 JSON 对象
        if value is None or not value.strip():
            return None
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            # 如果解析失败，返回 None
            return None
