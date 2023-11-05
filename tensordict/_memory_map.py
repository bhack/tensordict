# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import os
import tempfile
from typing import Optional, Union

import numpy as np
import torch
from torch import Tensor
from torch import memory_format
from torch.types import (
    _bool,
    _dtype,
    _layout,
    _device,
)
from multiprocessing import util
from multiprocessing.context import reduction

import sys

def empty_like(
    input: Tensor,
    *,
    memory_format: Optional[memory_format] = None,
    dtype: Optional[_dtype] = None,
    layout: Optional[_layout] = None,
    device: Optional[Union[_device, str, None]] = None,
    pin_memory: Optional[_bool] = False,
    requires_grad: Optional[_bool] = False,
    filename: Optional[str] = None
) -> Tensor:
    shape = input.shape
    if dtype is None:
        dtype = input.dtype
    if device is not None:
        device = torch.device(device)
        if device.type != "cpu":
            raise ValueError
    if filename is None:
        if dtype.is_floating_point:
            size = torch.finfo(dtype).bits // 8 * shape.numel()
        elif dtype.is_complex:
            raise ValueError(
                "Complex-valued tensors are not supported by memory-mapped tensors."
            )
        elif dtype == torch.bool:
            size = shape.numel()
        else:
            # assume integer
            size = torch.iinfo(dtype).bits // 8 * shape.numel()
        handler = FileHandler(size)
        if layout is not None:
            raise ValueError
        if pin_memory:
            raise ValueError
        out = torch.frombuffer(
            memoryview(handler.buffer), dtype=dtype,
            # layout=layout,
            device=device,
            # pin_memory=pin_memory,
            requires_grad=requires_grad
            )
        out = torch.reshape(out, shape)
    else:
        out = torch.from_file(
            str(filename),
            shared=True,
            dtype=dtype,
            size=shape.numel(),
            layout=layout,
            device=device, pin_memory=pin_memory, requires_grad=requires_grad
        ).view(input.shape)
    return out


def zeros_like(
    input: Tensor,
    *,
    memory_format: Optional[memory_format] = None,
    dtype: Optional[_dtype] = None,
    layout: Optional[_layout] = None,
    device: Optional[Union[_device, str, None]] = None,
    pin_memory: Optional[_bool] = False,
    requires_grad: Optional[_bool] = False,
    filename: Optional[str] = None
):
    return empty_like(input, memory_format=memory_format, dtype=dtype, layout=layout, device=device, pin_memory=pin_memory, requires_grad=requires_grad, filename=filename).zero_()

def ones_like(
    input: Tensor,
    *,
    memory_format: Optional[memory_format] = None,
    dtype: Optional[_dtype] = None,
    layout: Optional[_layout] = None,
    device: Optional[Union[_device, str, None]] = None,
    pin_memory: Optional[_bool] = False,
    requires_grad: Optional[_bool] = False,
    filename: Optional[str] = None
):
    return empty_like(input, memory_format=memory_format, dtype=dtype, layout=layout, device=device, pin_memory=pin_memory, requires_grad=requires_grad, filename=filename).fill_(1.0)


class FileHandler:
    if sys.platform == "linux":
        _dir_candidates = ["/dev/shm"]
    else:
        _dir_candidates = []

    def __init__(self, size, fd=-1, filename=None):
        # borrowed from mp.heap
        self.size = size
        # if filename is None:
        if fd == -1:
            self.fd, name = tempfile.mkstemp(
                prefix="pym-%d-" % os.getpid(), dir=self._choose_dir(size)
            )
            # self.filename = name
            os.unlink(name)
            util.Finalize(self, os.close, (self.fd,))
            os.ftruncate(self.fd, size)
        else:
            self.fd = fd
        # else:
        #     self.filename = filename
        self.buffer = mmap.mmap(self.fd, self.size)

    def _choose_dir(self, size):
        # Choose a non-storage backed directory if possible,
        # to improve performance
        for d in self._dir_candidates:
            st = os.statvfs(d)
            if st.f_bavail * st.f_frsize >= size:  # enough free space?
                return d
        tmpdir = util.get_temp_dir()
        return tmpdir


def reduce_handler(handler):
    if handler.fd == -1:
        raise ValueError(
            "Handler is unpicklable because " "forking was enabled when it was created"
        )
    return rebuild_handler, (handler.size, reduction.DupFd(handler.fd))


def rebuild_handler(size, dupfd):
    detached = dupfd.detach()
    return FileHandler(size, detached)

def from_tensor(tensor, *, filename=None, copy_existing=False):
    if filename is not None and tensor.storage().filename is not None and not copy_existing:
        raise ValueError(f"A filename was provided but the tensor already has a file associated ({tensor.storage().filename}). "
                         f"To copy the tensor onto the new location, pass copy_existing=True.")
    return empty_like(tensor, filename=filename).copy_(tensor)