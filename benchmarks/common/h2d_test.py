# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import argparse

import pytest
import torch
from packaging import version

from tensordict import TensorDict

TORCH_VERSION = version.parse(version.parse(torch.__version__).base_version)


@pytest.fixture(autouse=True, scope="function")
def empty_compiler_cache():
    torch._dynamo.reset_code_caches()
    yield


@pytest.fixture
def td():
    return TensorDict(
        {
            str(i): {str(j): torch.randn(16, 16, device="cpu") for j in range(16)}
            for i in range(16)
        },
        batch_size=[16],
        device="cpu",
    )


def _make_njt():
    lengths = torch.arange(24, 1, -1)
    offsets = torch.cat([lengths[:1] * 0, lengths]).cumsum(0)
    return torch.nested.nested_tensor_from_jagged(
        torch.arange(78, dtype=torch.float), offsets=offsets, lengths=lengths
    )


@pytest.fixture
def njt_td():
    return TensorDict(
        {str(i): {str(j): _make_njt() for j in range(32)} for i in range(32)},
        device="cpu",
    )


@pytest.fixture
def default_device():
    if torch.cuda.is_available():
        yield torch.device("cuda:0")
    elif torch.backends.mps.is_available():
        yield torch.device("mps:0")
    else:
        pytest.skip("CUDA/MPS is not available")


@pytest.mark.parametrize(
    "consolidated,compile_mode,num_threads",
    [
        [False, False, None],
        [True, False, None],
        [True, False, 4],
        [True, False, 16],
        [True, "default", 0],
    ],
)
@pytest.mark.skipif(
    TORCH_VERSION < version.parse("2.5.0"), reason="requires torch>=2.5"
)
class TestTo:
    def test_to(
        self, benchmark, consolidated, td, default_device, compile_mode, num_threads
    ):
        if consolidated:
            td = td.consolidate()

        def to(td, num_threads):
            return td.to(default_device, num_threads=num_threads)

        if compile_mode:
            to = torch.compile(to, mode=compile_mode)

        for _ in range(3):
            to(td, num_threads=num_threads)

        benchmark(to, td, num_threads)

    def test_to_njt(
        self, benchmark, consolidated, njt_td, default_device, compile_mode, num_threads
    ):
        if consolidated:
            njt_td = njt_td.consolidate()

        def to(td, num_threads):
            return td.to(default_device, num_threads=num_threads)

        if compile_mode:
            to = torch.compile(to, mode=compile_mode)

        for _ in range(3):
            to(njt_td, num_threads=num_threads)

        benchmark(to, njt_td, num_threads)


if __name__ == "__main__":
    args, unknown = argparse.ArgumentParser().parse_known_args()
    pytest.main(
        [__file__, "--capture", "no", "--exitfirst", "--benchmark-group-by", "func"]
        + unknown
    )
