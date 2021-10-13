#!/usr/bin/env python3
"""Simple example with ctypes.Structures."""

import ctypes
import multiprocessing
import os
import random
import time

import cv2
import numpy as np
import matplotlib.pyplot as plt

import ringbuffer
from image_generator import imgGenerator

# define size of images to be stored in buffer
IMG_WIDTH = 640
IMG_HEIGHT = 480
IMG_CHANNELS = 3


class Frame(ctypes.Structure):
    """c struct for representing frame and timestamp"""
    _fields_ = [
        ("timestamp_us", ctypes.c_ulonglong),
        ("frame", ctypes.c_ubyte * IMG_CHANNELS * IMG_WIDTH * IMG_HEIGHT)
    ]


def writer(ring, img_gen):
    
    i = 0

    while True:
        time_micros = int(time.time() * 10**6)

        # replace this with capture.read()
        img = next(img_gen)

        frame = Frame(time_micros, np.ctypeslib.as_ctypes(img))

        try:
            ring.try_write(frame)
        except ringbuffer.WaitingForReaderError:
            continue

        if i and i % 100 == 0:
            print('Wrote %d so far' % i)

        i += 1
        time.sleep(0.5)

    ring.writer_done()
    print('Writer is done')


def reader(ring, pointer, n):
    # time.sleep(2)

    while True:
        print("read")
        try:
            data = ring.blocking_read(pointer, length=n)
        except ringbuffer.WriterFinishedError:
            return

        # structured array
        tp = np.dtype(Frame)
        arr = np.frombuffer(data, dtype=tp)

        # accessing structured array 
        timestamps = arr["timestamp_us"]
        frames = arr["frame"]
       
        print(f"Reader saw records at timestamp {timestamps[0]} to {timestamps[1]}, frame_shape={frames.shape}")

        plt_img_sequence(data, f"read {n}")


    print('Reader %r is done' % id(pointer))


def plt_img_sequence(imgs, name: str):

    n = len(imgs)

    # compute the number of columns / rows needed dynamically
    ncols = int(n ** 0.5) # squares are good
    nrows = n // ncols
    nrows += 1 if (n % ncols) != 0 else 0

    # TODO: probably should use grid spec here, but it works
    fig = plt.figure()

    for i in range(n):

        img = imgs[i]

        ax = fig.add_subplot(nrows, ncols, i + 1)
        
        ax.imshow(img.frame)
        ax.set_title(f"{round((img.timestamp_us / 1e6), 3)} s")
        ax.tick_params(
            axis="both",
            which="both",
            bottom=False,
            labelbottom=False,
            left=False,
            labelleft=False
        )

    plt.suptitle(name)
    plt.tight_layout()
    plt.show()

def main():

    img_gen = imgGenerator(IMG_WIDTH, IMG_HEIGHT)

    ring = ringbuffer.RingBuffer(c_type=Frame, slot_count=30)
    ring.new_writer()

    processes = [
        multiprocessing.Process(target=reader, args=(ring, ring.new_reader(), 2,)),
        multiprocessing.Process(target=reader, args=(ring, ring.new_reader(), 8,)),
        multiprocessing.Process(target=writer, args=(ring, img_gen)),
    ]

    for p in processes:
        # p.daemon = True
        p.start()

    # for p in processes:
    #     p.join(timeout=20)
    #     assert not p.is_alive()
    #     assert p.exitcode == 0


if __name__ == '__main__':
    main()
