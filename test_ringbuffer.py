#!/usr/bin/env python3

import ctypes
import gc
import logging
import multiprocessing
import queue
import threading
import time
import unittest
import ringbuffer


class TestException(Exception):
    pass


class ReadersWriterLockTest(unittest.TestCase):
    def setUp(self):
        self.lock = ringbuffer.ReadersWriterLock()
        self.assert_unlocked()
        self.result_queues = {}

    def assert_unlocked(self):
        self.assertEqual(0, self.lock.readers.value)
        self.assertFalse(self.lock.writer.value)

    def assert_readers(self, count):
        self.assertEqual(count, self.lock.readers.value)
        self.assertFalse(self.lock.writer.value)

    def assert_writer(self):
        self.assertEqual(0, self.lock.readers.value)
        self.assertTrue(self.lock.writer.value)

    def reader_count(self):
        return self.lock.readers.value

    def async(self, func):
        def wrapper(result_queue):
            result = func()
            result_queue.put(result)

        result_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=wrapper, args=(result_queue, ))

        self.result_queues[process] = result_queue

        process.start()
        return process

    def get_result(self, process):
        process.join()
        return self.result_queues[process].get()

    def test_read_then_write(self):
        with self.lock.for_read():
            self.assert_readers(1)

        self.assert_unlocked()

        with self.lock.for_write():
            self.assert_writer()

        self.assert_unlocked()

    def test_reentrant_readers(self):
        with self.lock.for_read():
            self.assert_readers(1)

            with self.lock.for_read():
                self.assert_readers(2)

                with self.lock.for_read():
                    self.assert_readers(3)

                self.assert_readers(2)

            self.assert_readers(1)

        self.assert_unlocked()

    def test_writer_blocks_reader(self):
        with self.lock.for_write():
            event = multiprocessing.Event()

            def test():
                self.assert_writer()

                # Caller will block until this event is released.
                event.set()

                with self.lock.for_read():
                    self.assert_readers(1)
                    return 'read'

            r = self.async(test)

            # Wait until we can confirm that the reader is locked out.
            event.wait()
            self.assert_writer()

        self.assertEqual('read', self.get_result(r))
        self.assert_unlocked()

    def test_writer_blocks_multiple_readers(self):
        with self.lock.for_write():
            before_read = multiprocessing.Barrier(3)
            during_read = multiprocessing.Barrier(2)
            after_read = multiprocessing.Barrier(2)

            def test():
                self.assert_writer()

                before_read.wait()

                with self.lock.for_read():
                    during_read.wait()
                    value = self.reader_count()
                    after_read.wait()
                    return value

            r1 = self.async(test)
            r2 = self.async(test)

            # Wait until we can confirm that all readers are locked out
            before_read.wait()
            self.assert_writer()

        self.assertEqual(2, self.get_result(r1))
        self.assertEqual(2, self.get_result(r2))
        self.assert_unlocked()

    def test_reader_blocks_writer(self):
        with self.lock.for_read():
            before_write = multiprocessing.Barrier(2)

            def test():
                self.assert_readers(1)

                before_write.wait()

                with self.lock.for_write():
                    self.assert_writer()
                    return 'written'

            writer = self.async(test)

            # Wait until we can confirm that all writers are locked out.
            before_write.wait()
            self.assert_readers(1)

        self.assertEqual('written', self.get_result(writer))
        self.assert_unlocked()

    def test_multiple_readers_block_writer(self):
        with self.lock.for_read():
            before_read = multiprocessing.Barrier(3)
            after_read = multiprocessing.Barrier(2)

            def test_reader():
                self.assert_readers(1)

                with self.lock.for_read():
                    before_read.wait()
                    value = self.reader_count()
                    after_read.wait()
                    return value

            def test_writer():
                before_read.wait()

                with self.lock.for_write():
                    self.assert_writer()
                    return 'written'

            reader = self.async(test_reader)
            writer = self.async(test_writer)

            # Wait for the write to be blocked by multiple readers.
            before_read.wait()
            self.assert_readers(2)
            after_read.wait()

        self.assertEqual(2, self.get_result(reader))
        self.assertEqual('written', self.get_result(writer))
        self.assert_unlocked()

    def test_multiple_writers_block_each_other(self):
        with self.lock.for_write():
            before_write = multiprocessing.Barrier(2)

            def test():
                before_write.wait()

                with self.lock.for_write():
                    self.assert_writer()
                    return 'written'

            writer = self.async(test)

            before_write.wait()
            self.assert_writer()

        self.assertEqual('written', self.get_result(writer))
        self.assert_unlocked()

    def test_wait_for_write(self):
        event = multiprocessing.Event()
        wait_count = 0

        with self.lock.for_read():

            def test():
                with self.lock.for_write():
                    self.assert_writer()
                    event.set()
                    return 'written'

            writer = self.async(test)

            while not event.is_set():
                self.assert_readers(1)
                wait_count += 1
                self.lock.wait_for_write()
                self.assert_readers(1)

        self.assertEqual('written', self.get_result(writer))
        self.assert_unlocked()
        self.assertLessEqual(wait_count, 2)

    def test_wait_for_write__writer_already_waiting_for_reader(self):
        event = multiprocessing.Event()

        with self.lock.for_read():

            def test():
                event.set()
                with self.lock.for_write():
                    self.assert_writer()
                    event.set()
                    return 'written'

            writer = self.async(test)

            event.wait()
            # Force a context switch so the writer is waiting
            time.sleep(0.1)

            self.lock.wait_for_write()
            self.assert_readers(1)

        self.assertEqual('written', self.get_result(writer))
        self.assert_unlocked()

    def test_wait_for_write_without_lock(self):
        self.assert_unlocked()
        self.assertRaises(ringbuffer.InternalLockingError,
                          self.lock.wait_for_write)

    def test_unlock_readers_on_exception(self):
        try:
            with self.lock.for_read():
                self.assert_readers(1)
                raise TestException
        except TestException:
            self.assert_unlocked()
        else:
            self.fail()

    def test_unlock_writer_on_exception(self):
        try:
            with self.lock.for_write():
                self.assert_writer()
                raise TestException
        except TestException:
            self.assert_unlocked()
        else:
            self.fail()


class Expecter:
    def __init__(self, ring, pointer, testcase):
        self.ring = ring
        self.pointer = pointer
        self.testcase = testcase

    def expect_index(self, i):
        self.testcase.assertEqual(i, self.pointer.get().index)

    def write(self, data):
        self.ring.try_write(data)

    def write_multiple(self, data):
        self.ring.try_write_multiple(data)

    def _get_read_func(self, blocking):
        if blocking:
            return self.ring.blocking_read
        else:
            return self.ring.try_read

    def expect_read(self, expected_data, blocking=False):
        read = self._get_read_func(blocking)
        data = read(self.pointer)
        item = data[0]
        for k, v in expected_data.items():
            value = getattr(item, k)
            self.testcase.assertEqual(v, value, 'Data field {} was: {}'.format(
                k, value))

    def expect_multi_read(self, expected_data_list, length=1, blocking=False):
        read = self._get_read_func(blocking)
        data = read(self.pointer, length=length)
        self.testcase.assertEqual(
            len(expected_data_list), len(data), 'Data length is not correct')
        for i, expected_data in enumerate(expected_data_list):
            for k, v in expected_data.items():
                value = getattr(data[i], k)
                self.testcase.assertEqual(v, value,
                                          'Data field {} was: {}'.format(
                                              k, value))

    def expect_read_all(self, expected_data_list):
        data = self.ring.try_read_all(self.pointer)
        self.testcase.assertEqual(
            len(expected_data_list), len(data), 'Data length is not correct')
        for i, expected_data in enumerate(expected_data_list):
            for k, v in expected_data.items():
                value = getattr(data[i], k)
                self.testcase.assertEqual(v, value,
                                          'Data field {}: was {}'.format(
                                              k, value))

    def expect_waiting_for_writer(self):
        # There's no blocking version of this because the WaitingForWriterError
        # is what's used to determine when to block on the condition variable.
        self.testcase.assertRaises(ringbuffer.WaitingForWriterError,
                                   self.ring.try_read, self.pointer)

    def expect_waiting_for_reader(self):
        self.testcase.assertRaises(ringbuffer.WaitingForReaderError,
                                   self.ring.try_write, TStruct())

    def writer_done(self):
        self.ring.writer_done()

    def expect_writer_finished(self, blocking=False):
        read = self._get_read_func(blocking)
        self.testcase.assertRaises(ringbuffer.WriterFinishedError, read,
                                   self.pointer)

    def expect_already_closed(self):
        self.testcase.assertRaises(ringbuffer.AlreadyClosedError,
                                   self.ring.try_write, TStruct())

    def force_reader_sync(self):
        self.ring.force_reader_sync()

    def expect_try_read_type(self, type_or_class):
        data = self.ring.try_read(self.pointer)
        self.testcase.assertTrue(isinstance(data, type_or_class))


class AsyncProxy:
    def __init__(self, expecter, in_queue, error_queue):
        self.expecter = expecter

        self.in_queue = in_queue
        self.error_queue = error_queue
        self.runner = None

    def run(self):
        while True:
            item = self.in_queue.get()
            try:
                if item == 'done':
                    logging.debug('Exiting %r', self.runner)
                    return

                name, args, kwargs = item
                logging.debug('Running %s(%r, %r)', name, args, kwargs)
                try:
                    getattr(self.expecter, name)(*args, **kwargs)
                except Exception as e:
                    logging.exception('Problem running %s(*%r, **%r)', name,
                                      args, kwargs)
                    self.error_queue.put(e)
            finally:
                self.in_queue.task_done()

    def shutdown(self):
        self.in_queue.put('done')

    def __getattr__(self, name):
        def proxy(*args, **kwargs):
            self.expecter.testcase.assertTrue(
                self.runner,
                'Must call start_proxies() before setting test expectations')

            # This queue is used to sequence operations between functions
            # that are running asynchronously (threads or processes).
            self.in_queue.put((name, args, kwargs))

            # If this test function is running in blocking mode, that means
            # the locking and sequencing is built into the semantics of the
            # function call itself. That means we can skip waiting for the
            # asynchronous function to consume the queue before letting
            # subsequent test methods run.
            if kwargs.get('blocking'):
                # Allow a context switch so the asynchronous function has
                # a chance to actually start the function call.
                time.sleep(0.1)
            else:
                self.in_queue.join()

        return proxy


class TStruct(ctypes.Structure):
    _fields_ = (('i', ctypes.c_int32), ('f', ctypes.c_float))


class RingBufferTestBase:
    def setUp(self):
        self.ring = ringbuffer.RingBuffer(c_type=TStruct, slot_count=10)
        self.proxies = []
        self.error_queue = self.new_queue()

    def tearDown(self):
        for proxy in self.proxies:
            if proxy.runner:
                proxy.shutdown()
        for proxy in self.proxies:
            if proxy.runner:
                proxy.in_queue.join()
        if not self.error_queue.empty():
            raise self.error_queue.get()

        # Force child processes and pipes to be garbage collected, otherwise
        # we'll run out of file descriptors.
        gc.collect()

    def new_queue(self):
        raise NotImplementedError

    def run_proxy(self, proxy):
        raise NotImplementedError

    def start_proxies(self):
        for proxy in self.proxies:
            self.run_proxy(proxy)

    def new_reader(self):
        expecter = Expecter(self.ring, self.ring.new_reader(), self)
        proxy = AsyncProxy(expecter, self.new_queue(), self.error_queue)
        self.proxies.append(proxy)
        return proxy

    def new_writer(self):
        self.ring.new_writer()
        expecter = Expecter(self.ring, self.ring.writer, self)
        proxy = AsyncProxy(expecter, self.new_queue(), self.error_queue)
        self.proxies.append(proxy)
        return proxy

    def test_write_simple(self):
        writer = self.new_writer()
        self.start_proxies()
        o = TStruct(i=22, f=2.2)
        writer.write(o)

    def test_write_string(self):
        writer = self.new_writer()
        self.start_proxies()
        self.assertTrue(self.error_queue.empty())
        writer.write('this does not work')
        error = self.error_queue.get()
        self.assertTrue(isinstance(error, TypeError))

    def _do_read_single_write(self, blocking):
        reader = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        writer.expect_index(0)
        o = TStruct(i=22, f=2.2)
        writer.write(o)
        writer.expect_index(1)

        reader.expect_index(0)
        reader.expect_read({'i': 22}, blocking=blocking)
        reader.expect_index(1)

    def test_read_single_write_blocking(self):
        self._do_read_single_write(True)

    def test_read_single_write_non_blocking(self):
        self._do_read_single_write(False)

    def _do_read_ahead_of_writes(self, blocking):
        reader = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        reader.expect_waiting_for_writer()
        o = TStruct(i=22, f=2.2)
        writer.write(o)
        reader.expect_read({'i': 22}, blocking=blocking)

    def test_read_ahead_of_writes_blocking(self):
        self._do_read_ahead_of_writes(True)

    def test_read_ahead_of_writes_non_blocking(self):
        self._do_read_ahead_of_writes(False)

    def _do_two_reads_one_behind_one_ahead(self, blocking):
        r1 = self.new_reader()
        r2 = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        o = TStruct(i=22, f=2.2)
        writer.write(o)

        r1.expect_read({'i': 22}, blocking=blocking)
        r1.expect_waiting_for_writer()

        r2.expect_read({'i': 22}, blocking=blocking)
        r2.expect_waiting_for_writer()

    def test_two_reads_one_behind_one_ahead_blocking(self):
        self._do_two_reads_one_behind_one_ahead(True)

    def test_two_reads_one_behind_one_ahead_non_blocking(self):
        self._do_two_reads_one_behind_one_ahead(False)

    def test_write_conflict_first_slot(self):
        reader = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        for i in range(self.ring.slot_count):
            o = TStruct(i=i, f=2.2)
            writer.write(o)

        # The writer has wrapped around and is now waiting for the reader
        # to free up a slot. They have the same index, but are different
        # generations.
        reader.expect_index(0)
        writer.expect_index(0)
        writer.expect_waiting_for_reader()

        reader.expect_read({'i': 0})
        o = TStruct(i=1111, f=2.2)
        writer.write(o)

        for i in range(1, self.ring.slot_count):
            reader.expect_read({'i': i})

        reader.expect_index(0)
        reader.expect_read({'i': 1111})

    def test_write_conflict_last_slot(self):
        reader = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        last_slot = self.ring.slot_count - 1
        self.assertGreater(last_slot, 0)

        for i in range(last_slot):
            writer.write(TStruct(i=i))
            reader.expect_read({'i': i})

        writer.expect_index(last_slot)
        reader.expect_index(last_slot)

        # The reader's pointed at the last slot, now wrap around the writer
        # to catch up. They'll have the same index, but different generation
        # numbers.
        for i in range(self.ring.slot_count):
            writer.write(TStruct(i=self.ring.slot_count + i))

        reader.expect_index(last_slot)
        writer.expect_index(last_slot)
        writer.expect_waiting_for_reader()

        reader.expect_read({'i': self.ring.slot_count})
        writer.write(TStruct())
        writer.expect_index(0)
        reader.expect_index(0)

    def test_create_reader_after_writing(self):
        writer = self.new_writer()
        self.start_proxies()

        self.new_reader()  # No error because no writes happened yet.

        writer.write(TStruct())
        self.assertRaises(ringbuffer.MustCreatedReadersBeforeWritingError,
                          self.new_reader)

    def _do_read_after_close_beginning(self, blocking):
        reader = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        writer.writer_done()
        reader.expect_writer_finished(blocking=blocking)

    def test_read_after_close_beginning_blocking(self):
        self._do_read_after_close_beginning(True)

    def test_read_after_close_beginning_non_blocking(self):
        self._do_read_after_close_beginning(False)

    def _do_close_before_read(self, blocking):
        reader = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        writer.write(TStruct(i=4545))
        writer.writer_done()
        writer.expect_index(1)

        reader.expect_read({'i': 4545})
        reader.expect_writer_finished(blocking=blocking)
        reader.expect_index(1)

    def test_close_before_read_blocking(self):
        self._do_close_before_read(True)

    def test_close_before_read_non_blocking(self):
        self._do_close_before_read(False)

    def _do_close_after_read(self, blocking):
        reader = self.new_reader()
        writer = self.new_writer()
        self.start_proxies()

        writer.write(TStruct(i=3434))

        reader.expect_read({'i': 3434})
        reader.expect_waiting_for_writer()
        reader.expect_index(1)

        writer.writer_done()
        writer.expect_index(1)

        reader.expect_writer_finished(blocking=blocking)

    def test_close_after_read_blocking(self):
        self._do_close_after_read(True)

    def test_close_after_read_non_blocking(self):
        self._do_close_after_read(False)

    def test_close_then_write(self):
        writer = self.new_writer()
        self.start_proxies()

        writer.write(TStruct())
        writer.writer_done()
        writer.expect_already_closed()

    def test_blocking_readers_wake_up_after_write(self):
        writer = self.new_writer()
        r1 = self.new_reader()
        r2 = self.new_reader()
        self.start_proxies()

        r1.expect_read({'i': 11}, blocking=True)
        r2.expect_read({'i': 11}, blocking=True)

        writer.write(TStruct(i=11))

    def test_blocking_readers_wake_up_after_close(self):
        writer = self.new_writer()
        r1 = self.new_reader()
        r2 = self.new_reader()
        self.start_proxies()

        r1.expect_writer_finished(blocking=True)
        r2.expect_writer_finished(blocking=True)

        writer.writer_done()

    def test_force_reader_sync(self):
        writer = self.new_writer()
        r1 = self.new_reader()
        r2 = self.new_reader()
        self.start_proxies()

        writer.write(TStruct(i=1))
        writer.write(TStruct(i=2))
        writer.write(TStruct(i=3))

        writer.expect_index(3)
        r1.expect_index(0)
        r2.expect_index(0)

        writer.force_reader_sync()
        r1.expect_index(3)
        r2.expect_index(3)

    def _do_multiple_writers(self, blocking):
        w1 = self.new_writer()
        w2 = self.new_writer()
        reader = self.new_reader()
        self.start_proxies()

        w1.write(TStruct(i=11))
        w1.expect_index(1)
        w2.expect_index(1)

        w2.write(TStruct(i=22))
        w1.expect_index(2)
        w2.expect_index(2)

        w2.write(TStruct(i=33))
        w1.expect_index(3)
        w2.expect_index(3)

        w1.write(TStruct(i=44))
        w1.expect_index(4)
        w2.expect_index(4)

        reader.expect_read({'i': 11}, blocking=blocking)
        reader.expect_read({'i': 22}, blocking=blocking)
        reader.expect_read({'i': 33}, blocking=blocking)
        reader.expect_read({'i': 44}, blocking=blocking)

    def test_multiple_writers_blocking(self):
        self._do_multiple_writers(True)

    def test_multiple_writers_non_blocking(self):
        self._do_multiple_writers(False)

    def _do_test_multiple_writers_close(self, blocking):
        w1 = self.new_writer()
        w2 = self.new_writer()
        reader = self.new_reader()
        self.start_proxies()

        w1.write(TStruct(i=11))
        w1.writer_done()

        w2.write(TStruct(i=22))
        w2.writer_done()

        reader.expect_read({'i': 11}, blocking=blocking)
        reader.expect_read({'i': 22}, blocking=blocking)
        reader.expect_writer_finished(blocking=blocking)

    def test_multiple_writers_close_blocking(self):
        self._do_test_multiple_writers_close(True)

    def test_multiple_writers_close_non_blocking(self):
        self._do_test_multiple_writers_close(False)

    def _do_start_read_before_writer_setup(self, blocking):
        reader = self.new_reader()
        self.start_proxies()
        reader.expect_writer_finished(blocking=blocking)

    def test_start_read_before_writer_setup_blocking(self):
        self._do_start_read_before_writer_setup(True)

    def test_start_read_before_writer_setup_non_blocking(self):
        self._do_start_read_before_writer_setup(False)

    def test_read_older_gen(self):
        w = self.new_writer()
        reader = self.new_reader()
        self.start_proxies()

        for i in range(0, 10):
            w.write(TStruct(i=i))

        reader.expect_multi_read(
            [{
                'i': 0
            }, {
                'i': 1
            }, {
                'i': 2
            }, {
                'i': 3
            }, {
                'i': 4
            }], length=5)

        for i in range(10, 15):
            w.write(TStruct(i=i))

        reader.expect_multi_read(
            [{
                'i': 5
            }, {
                'i': 6
            }, {
                'i': 7
            }, {
                'i': 8
            }, {
                'i': 9
            }, {
                'i': 10
            }, {
                'i': 11
            }],
            length=7)
        w.writer_done()

    def test_read_all(self):
        w = self.new_writer()
        reader = self.new_reader()
        self.start_proxies()

        for i in range(0, 10):
            w.write(TStruct(i=i))

        expected_data = [{'i': index} for index in range(0, 10)]
        reader.expect_read_all(expected_data)

        for i in range(10, 15):
            w.write(TStruct(i=i))

        expected_data = [{'i': index} for index in range(10, 15)]
        reader.expect_read_all(expected_data)

        w.writer_done()


class ThreadingTest(RingBufferTestBase, unittest.TestCase):
    def new_queue(self):
        return queue.Queue()

    def run_proxy(self, proxy):
        thread = threading.Thread(target=proxy.run)
        proxy.runner = thread
        thread.daemon = True
        thread.start()


class MultiprocessingTest(RingBufferTestBase, unittest.TestCase):
    def new_queue(self):
        return multiprocessing.JoinableQueue()

    def run_proxy(self, proxy):
        process = multiprocessing.Process(target=proxy.run)
        proxy.runner = process
        process.daemon = True
        process.start()


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
