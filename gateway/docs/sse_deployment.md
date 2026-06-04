# SSE deployment notes

## Nginx reverse proxy

SSE must not be buffered by the proxy. Use a dedicated location for job streams:

```nginx
location /api/v1/jobs/ {
  proxy_pass http://gateway:8080;

  proxy_http_version 1.1;
  proxy_set_header Connection "";
  proxy_buffering off;
  proxy_cache off;
  proxy_read_timeout 1h;
  proxy_send_timeout 1h;
  chunked_transfer_encoding off;

  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
  proxy_set_header Last-Event-ID $http_last_event_id;
}
```

## Client example

```javascript
const es = new EventSource(`/api/v1/jobs/${jobId}/stream`, {
  withCredentials: true,
});

es.addEventListener('progress', (event) => {
  const data = JSON.parse(event.data);
  console.log(data.progress, data.progress_stage);
});

es.addEventListener('completed', (event) => {
  const data = JSON.parse(event.data);
  console.log('done', JSON.parse(data.result));
  es.close();
});

es.addEventListener('failed', (event) => {
  const data = JSON.parse(event.data);
  console.error(data.error);
  es.close();
});

es.onerror = (event) => {
  console.warn('SSE error; browser will auto-reconnect', event);
};
```

## Authentication

Browser `EventSource` cannot set custom headers. For production, prefer same-site cookies.
Query-string tokens are easy to debug but can leak into access logs, so keep them for local tools only.

## Capacity notes

Each SSE subscription consumes one gateway connection and one proxy connection. For 1000 concurrent streams,
set `worker_connections` above 1024 and watch active connection metrics in W6.
