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
            return orjson.dumps(value)
        except (TypeError, ValueError):
            # 如果 value 已经是字符串，则直接返回
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
