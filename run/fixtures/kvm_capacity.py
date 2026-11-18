"""Measure whether the runner can create a KVM guest exposing AMD-V or VT-x."""

import array
import errno
import fcntl
import json
import os
import struct

KVM_GET_API_VERSION = 0xAE00
KVM_CREATE_VM = 0xAE01
KVM_GET_SUPPORTED_CPUID = 0xC008AE05
ENTRY = struct.Struct("=10I")


def measure():
    result = {"create_vm": False}
    try:
        with open("/dev/kvm", "rb+", buffering=0) as kvm:
            result["api_version"] = fcntl.ioctl(kvm, KVM_GET_API_VERSION)
            vm_fd = fcntl.ioctl(kvm, KVM_CREATE_VM, 0)
            os.close(vm_fd)
            result["create_vm"] = True
            # kvm_cpuid2 is an eight-byte header and an array of 40-byte entries.
            capacity = 256
            items = array.array("B", bytes(8 + capacity * ENTRY.size))
            struct.pack_into("=I", items, 0, capacity)
            fcntl.ioctl(kvm, KVM_GET_SUPPORTED_CPUID, items, True)
            count, = struct.unpack_from("=I", items)
            assert count <= capacity
            features = {}
            for index in range(count):
                leaf, subleaf, _, _, _, ecx, *_ = ENTRY.unpack_from(items, 8 + index * ENTRY.size)
                if subleaf == 0:
                    features[leaf] = ecx
            result["guest_vmx"] = bool(features.get(1, 0) & (1 << 5))
            result["guest_svm"] = bool(features.get(0x80000001, 0) & (1 << 2))
    except OSError as error:
        result["errno"] = errno.errorcode.get(error.errno, str(error.errno))
    return result


if __name__ == "__main__":
    print(json.dumps(measure(), sort_keys=True))
