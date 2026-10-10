import socket,subprocess,threading,tempfile,time,selectors
from pathlib import Path

def run(mode, module, fixture):
    data=bytearray(); errors=[]
    listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',19452));listener.listen(1);listener.settimeout(8)
    def proxy():
        try:
            incoming,_=listener.accept(); outgoing=socket.create_connection(('127.0.0.1',19453),timeout=3)
            with incoming,outgoing,selectors.DefaultSelector() as selection:
                incoming.setblocking(False);outgoing.setblocking(False)
                selection.register(incoming,selectors.EVENT_READ,outgoing);selection.register(outgoing,selectors.EVENT_READ,incoming)
                while True:
                    ready=selection.select(8)
                    if not ready:break
                    for key,_ in ready:
                        block=key.fileobj.recv(65536)
                        if not block:return
                        if key.fileobj is incoming:data.extend(block)
                        key.data.sendall(block)
        except Exception as exc:errors.append(type(exc).__name__)
    receiver=subprocess.Popen(['ffmpeg','-nostdin','-loglevel','quiet','-listen','1','-i','rtmp://127.0.0.1:19453/probe/test','-c','copy','-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    time.sleep(.3);thread=threading.Thread(target=proxy,daemon=True);thread.start()
    server=None
    with tempfile.TemporaryDirectory(prefix='goats-native-meta-') as folder:
        root=Path(folder);config=root/'nginx.conf'
        if mode!='direct':
            config.write_text(f'load_module {module};\nworker_processes 1;pid {root}/nginx.pid;error_log {root}/error.log warn;events {{worker_connections 32;}}http {{access_log off;}}rtmp {{access_log off;server {{listen 127.0.0.1:19451;application probe {{live on;record off;meta {mode};push rtmp://127.0.0.1:19452/probe/test;}}}}}}')
            server=subprocess.Popen(['nginx','-p',folder,'-c',str(config),'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(.3)
        address='rtmp://127.0.0.1:'+('19452' if mode=='direct' else '19451')+'/probe/test'
        sender=subprocess.run(['ffmpeg','-nostdin','-loglevel','quiet','-re','-i',str(fixture),'-t','2','-c','copy','-f','flv',address],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12)
        if server:server.terminate();server.wait(timeout=5)
        thread.join(2);receiver.terminate();receiver.wait(timeout=5);listener.close()
        first=data.find(b'\x02\x00\x0aonMetaData');wrapper=data.find(b'\x02\x00\x0d@setDataFrame')
        print({'mode':mode,'sender_exit':sender.returncode,'metadata_found':first>=0,'setDataFrame_found':wrapper>=0,'captured_bytes':len(data),'errors':errors},flush=True)
        return first>=0,wrapper>=0
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Isolated native RTMP metadata regression check; no external endpoints.')
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True, help='Existing H.264/AAC media with at least two seconds of video')
    args = parser.parse_args()
    ports = (19451, 19452, 19453)
    occupied = []
    for port in ports:
        probe = socket.socket()
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            occupied.append(port)
        finally:
            probe.close()
    if occupied:
        raise SystemExit(f'Refusing isolated metadata test; loopback ports occupied: {occupied}')
    if not args.module.is_file() or not args.fixture.is_file():
        raise SystemExit('Module and fixture must both be regular files')
    for mode, expected in [('on', False), ('copy', False), ('publish', True)]:
        metadata, wrapped = run(mode, str(args.module.resolve()), args.fixture.resolve())
        if not metadata or wrapped != expected:
            raise SystemExit(f'Metadata check failed for {mode}')
    print('Native RTMP metadata checks passed')
