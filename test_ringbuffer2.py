import ringbuffer
import ctypes

class TStruct(ctypes.Structure):
    _fields_ = (('i', ctypes.c_int32), ('f', ctypes.c_float))


def test_ringbuffer_write_multiple():
    ring = ringbuffer.RingBuffer(c_type=TStruct, slot_count=10)
    ring.new_writer()
    reader = ring.new_reader()

    data = (TStruct * 8)()
    for i in range(0, 8):
        data[i] = TStruct(i=i)

    ring.try_write_multiple(data)

    expected_data_list = [{'i': index} for index in range(0, 6)]
    received_data = ring.try_read(reader, length=6)
    for i, expected_data in enumerate(expected_data_list):
        for k, v in expected_data.items():
            value = getattr(received_data[i], k)
            assert value == v

    data = (TStruct * 6)()
    for i in range(8, 14):
        data[i - 8] = TStruct(i=i)

    ring.try_write_multiple(data)

    expected_data_list = [{'i': index} for index in range(6, 14)]
    received_data = ring.try_read(reader, length=8)
    for i, expected_data in enumerate(expected_data_list):
        for k, v in expected_data.items():
            value = getattr(received_data[i], k)
            assert value == v
