#!/usr/bin/env python3
"""Simple example with ctypes.Structures."""

import ctypes
import multiprocessing
import os
import random
import time
import collections

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

def print_cap_props(capture: cv2.VideoCapture):

    props = {
        "CAP_PROP_FRAME_WIDTH": cv2.CAP_PROP_FRAME_WIDTH,
        "CAP_PROP_FRAME_HEIGHT": cv2.CAP_PROP_FRAME_HEIGHT,
        "CAP_PROP_FPS": cv2.CAP_PROP_FPS,
        "CAP_PROP_FOURCC": cv2.CAP_PROP_FOURCC,
        "CAP_PROP_BUFFERSIZE": cv2.CAP_PROP_BUFFERSIZE,
        "CAP_PROP_CONVERT_RGB": cv2.CAP_PROP_CONVERT_RGB,
        "CAP_PROP_AUTO_WB": cv2.CAP_PROP_AUTO_WB,
        "CAP_PROP_BACKEND": cv2.CAP_PROP_BACKEND,
        "CAP_PROP_CODEC_PIXEL_FORMAT": cv2.CAP_PROP_CODEC_PIXEL_FORMAT,
        # "CAP_PROP_HW_ACCELERATION": cv2.CAP_PROP_HW_ACCELERATION,
        # "CAP_PROP_HW_DEVICE": cv2.CAP_PROP_HW_DEVICE,
        # "CAP_PROP_HW_ACCELERATION_USE_OPENCL": cv2.CAP_PROP_HW_ACCELERATION_USE_OPENCL,
    }

    for key, val in props.items():
        print(f"{key:>35} ={capture.get(val):14.2f}")

class FPS:
    def __init__(self,avarageof=50):
        self.frametimestamps = collections.deque(maxlen=avarageof)
    def __call__(self):
        self.frametimestamps.append(time.time())
        if(len(self.frametimestamps) > 1):
            return round(len(self.frametimestamps)/(self.frametimestamps[-1]-self.frametimestamps[0]), 2)
        else:
            return 0.0


def writer(ring, img_gen):
    
    cap = cv2.VideoCapture(0)
    # cap.set(cv2.CAP_PROP_FPS, 5)
    # cap.set(cv2.CAP_PROP_BUFFERSIZE, 0)

    print_cap_props(cap)


    i = 0
    fps = FPS()

    recording_freq = 0.060 # ~ 15 fps
    # recording_freq = 0.030 # ~ 30 fps


    print(recording_freq)

    img = np.zeros((IMG_WIDTH, IMG_HEIGHT, IMG_CHANNELS))

    while True:

        # replace this with capture.read()
        # img = next(img_gen)
        time_s = time.time()

        while True:
            ret = cap.grab()
            if (time.time() - time_s) > recording_freq:
                break

        ret, img = cap.retrieve()

        print(f"{fps()} fps")

        img = cv2.resize(img, (IMG_WIDTH, IMG_HEIGHT))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.flip(img, 1)

        if not ret:
            break

        frame = Frame(int(time_s * 10e6), np.ctypeslib.as_ctypes(img))

        try:
            ring.try_write(frame)
        except ringbuffer.WaitingForReaderError:
            continue

        if i and i % 100 == 0:
            print('Wrote %d so far' % i)

        i += 1
        cv2.waitKey(1)

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
