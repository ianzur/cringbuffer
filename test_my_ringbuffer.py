
import ctypes
import multiprocessing

import ringbuffer

class Test(ctypes.Structure):
    """c struct for representing single int"""
    _fields_ = [
        ("int", ctypes.c_uint),
    ]

def writer(ring, n):

    for i in range(n):

        ring.write(Test(i))

    # ring.writer_done()

def reader(ring, n):

    a = ring.blocking_read(n)
    
    print(f"read n={n} {list(i.int for i in a)}")


if __name__ == "__main__":

    ring = ringbuffer.RingBuffer(c_type=Test, slot_count=8)
    ring.new_writer()

    proc_writer = multiprocessing.Process(target=writer, args=(ring, 12))
    proc_writer.start()

    proc_writer.join()
    assert not proc_writer.is_alive()

    processes = [
        multiprocessing.Process(target=reader, args=(ring, 1)),
        multiprocessing.Process(target=reader, args=(ring, 2)),
        multiprocessing.Process(target=reader, args=(ring, 3)),
        multiprocessing.Process(target=reader, args=(ring, 4)),
        multiprocessing.Process(target=reader, args=(ring, 5)),
        multiprocessing.Process(target=reader, args=(ring, 6)),
        multiprocessing.Process(target=reader, args=(ring, 7)),
        multiprocessing.Process(target=reader, args=(ring, 8)),
        # multiprocessing.Process(target=reader, args=(ring, 11)),
    ]

    for p in processes:
        p.start()

    for p in processes:
        p.join()




