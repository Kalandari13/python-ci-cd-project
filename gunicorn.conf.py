"""Origin server settings; external scheme/host come from PUBLIC_ORIGIN."""
import os

bind = '0.0.0.0:5000'
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = 4
timeout = 30
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100
worker_tmp_dir = '/tmp'
# Do not trust arbitrary X-Forwarded-* headers. Our app uses an explicit origin.
forwarded_allow_ips = ''
accesslog = '-'
errorlog = '-'
# Exclude query strings, request headers, and request bodies from access logs.
access_log_format = '%(m)s %(U)s %(s)s %(L)s'
