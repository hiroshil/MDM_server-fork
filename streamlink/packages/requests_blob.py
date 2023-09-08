'''
Copyright 2015 Red Hat, Inc.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
'''
from io import BytesIO
import threading
from requests.adapters import BaseAdapter
from requests.compat import urlparse
from requests import Response, codes
from uuid import uuid4
url_bytesIo = {}
url_bytesIo_lock = threading.Lock()

class MyBytesIO(BytesIO):
    __doc__ = 'docstring for MyBytesIO'

    def __init__(self, id, data):
        super(MyBytesIO, self).__init__(data)
        self.id = id
        self.content_length = len(data)

    def close(self):
        with url_bytesIo_lock:
            if self.id in url_bytesIo:
                del url_bytesIo[self.id]
        super(MyBytesIO, self).close()

def createBlobUrl(data):
    id_url = str(uuid4())
    url = 'blob://' + id_url
    with url_bytesIo_lock:
        url_bytesIo[id_url] = MyBytesIO(id_url, data if isinstance(data, bytes) else data.encode('utf-8'))
    return url

class BlobAdapter(BaseAdapter):

    def send(self, request, **kwargs):
        ''' Wraps a file, described in request, in a Response object.

            :param request: The PreparedRequest` being "sent".
            :returns: a Response object containing the file
        '''
        if request.method not in ('GET', 'HEAD'):
            raise ValueError('Invalid request method %s' % request.method)
        url_parts = urlparse(request.url)
        resp = Response()
        resp.url = request.url
        with url_bytesIo_lock:
            if url_parts.netloc in url_bytesIo:
                resp.raw = url_bytesIo[url_parts.netloc]
                resp.raw.release_conn = resp.raw.close
                resp.status_code = codes.ok
                resp.headers['Content-Length'] = resp.raw.content_length
            else:
                resp.raw = BytesIO(b'Not Found')
                resp.raw.release_conn = resp.raw.close
                resp.headers['Content-Length'] = 9
                resp.status_code = codes.not_found
        return resp

    def close(self):
        pass

