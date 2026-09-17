"""One bounded ASR subprocess per material batch, reused across videos."""
import json
import os
import selectors
import subprocess
import time
import uuid
from pathlib import Path


class WorkerError(Exception):
    def __init__(self, code, message):
        super().__init__(message);self.code=code


class TranscriptionWorker:
    def __init__(self, python, model, log_path, timeout=3600):
        self.python, self.model, self.log_path = python, model, Path(log_path)
        self.timeout, self.process, self.log = timeout, None, None

    def start(self):
        if self.process is not None and self.process.poll() is None:return
        self.close()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log=self.log_path.open('ab')
        self.process=subprocess.Popen([str(self.python),'-u',str(Path(__file__).with_name('transcribe_local.py')),
            '--worker','--model-path',str(self.model)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=self.log,bufsize=0)

    def transcribe(self, video, output, cache):
        try:
            self.start()
            rid=uuid.uuid4().hex
            request={'request_id':rid,'video':str(video),'output':str(output),'cache':str(cache)}
            self.process.stdin.write((json.dumps(request)+'\n').encode());self.process.stdin.flush()
            deadline=time.monotonic()+self.timeout;buffer=b''
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout,selectors.EVENT_READ)
                while b'\n' not in buffer:
                    remaining=deadline-time.monotonic()
                    if remaining<=0 or not selector.select(remaining):
                        raise WorkerError('timeout','转录超时；已保存的片段可用于续跑')
                    chunk=os.read(self.process.stdout.fileno(),65536)
                    if not chunk:raise WorkerError('worker_failed','转录进程已退出，详见批次运行日志')
                    buffer+=chunk
                    if len(buffer)>1024*1024:raise WorkerError('worker_failed','转录进程返回异常长度')
            result=json.loads(buffer.split(b'\n',1)[0])
            if result.get('request_id')!=rid:raise WorkerError('worker_failed','转录回执与当前任务不匹配')
            if not result.get('ok'):raise WorkerError(result.get('code','transcription_failed'),result.get('message','转录失败'))
            return result['result']
        except Exception:
            self.close()
            raise

    def close(self):
        if self.process:
            try:
                if self.process.poll() is None:
                    # EOF lets an idle model cleanly release its runtime resources.
                    if self.process.stdin:self.process.stdin.close()
                    try:self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.process.terminate()
                        try:self.process.wait(timeout=3)
                        except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            finally:
                for stream in (self.process.stdin,self.process.stdout):
                    if stream:stream.close()
                self.process=None
        if self.log:self.log.close();self.log=None

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
