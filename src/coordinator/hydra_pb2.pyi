from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class TaskStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    QUEUED: _ClassVar[TaskStatus]
    STARTED: _ClassVar[TaskStatus]
    COMPLETE: _ClassVar[TaskStatus]
    FAILED: _ClassVar[TaskStatus]
QUEUED: TaskStatus
STARTED: TaskStatus
COMPLETE: TaskStatus
FAILED: TaskStatus

class TaskRequest(_message.Message):
    __slots__ = ("task_id", "data")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    data: str
    def __init__(self, task_id: _Optional[str] = ..., data: _Optional[str] = ...) -> None: ...

class TaskResponse(_message.Message):
    __slots__ = ("task_id", "message", "success")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    message: str
    success: bool
    def __init__(self, task_id: _Optional[str] = ..., message: _Optional[str] = ..., success: bool = ...) -> None: ...

class ClientTaskRequest(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: str
    def __init__(self, data: _Optional[str] = ...) -> None: ...

class ClientTaskResponse(_message.Message):
    __slots__ = ("message", "task_id")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    message: str
    task_id: str
    def __init__(self, message: _Optional[str] = ..., task_id: _Optional[str] = ...) -> None: ...

class HeartbeatRequest(_message.Message):
    __slots__ = ("workerId", "address")
    WORKERID_FIELD_NUMBER: _ClassVar[int]
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    workerId: int
    address: str
    def __init__(self, workerId: _Optional[int] = ..., address: _Optional[str] = ...) -> None: ...

class HeartbeatResponse(_message.Message):
    __slots__ = ("acknowledged",)
    ACKNOWLEDGED_FIELD_NUMBER: _ClassVar[int]
    acknowledged: bool
    def __init__(self, acknowledged: bool = ...) -> None: ...

class UpdateTaskStatusRequest(_message.Message):
    __slots__ = ("task_id", "status", "started_at", "completed_at", "failed_at")
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_AT_FIELD_NUMBER: _ClassVar[int]
    FAILED_AT_FIELD_NUMBER: _ClassVar[int]
    task_id: str
    status: TaskStatus
    started_at: int
    completed_at: int
    failed_at: int
    def __init__(self, task_id: _Optional[str] = ..., status: _Optional[_Union[TaskStatus, str]] = ..., started_at: _Optional[int] = ..., completed_at: _Optional[int] = ..., failed_at: _Optional[int] = ...) -> None: ...

class UpdateTaskStatusResponse(_message.Message):
    __slots__ = ("success",)
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    def __init__(self, success: bool = ...) -> None: ...
