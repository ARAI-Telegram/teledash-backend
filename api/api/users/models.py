from enum import Enum


class UserSearchField(str, Enum):
    USERNAME = "username"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
