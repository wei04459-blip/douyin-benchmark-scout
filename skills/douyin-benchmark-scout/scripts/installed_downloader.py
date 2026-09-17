#!/usr/bin/env python3
"""Bounded adapter for the user's installed Douyin_TikTok_Download_API."""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse
from research_batch import now, save


class ProviderError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def normalize(data, aid):
    item = data.get('aweme_detail') if isinstance(data, dict) else None
    if not isinstance(item, dict):
        raise ProviderError('missing_video_data')
    if str(item.get('aweme_id')) != aid:
        raise ProviderError('identity_mismatch')
    video = item.get('video') or {}
    # Use a publisher-provided readable rendition; original high bitrate is unnecessary for research.
    choices = [video.get('play_addr') or {}]
    choices.extend((b.get('play_addr') or {}) for b in video.get('bit_rate', []) if isinstance(b,dict) and b.get('format') == 'mp4')
    choices = [a for a in choices if a.get('url_list')]
    readable = [a for a in choices if min(a.get('width') or 0,a.get('height') or 0)>=540]
    chosen = min(readable or choices, key=lambda a:a.get('data_size') or float('inf')) if choices else {}
    urls = chosen.get('url_list') or []
    valid = [u for u in urls if isinstance(u,str) and urlparse(u).scheme == 'https']
    duration = video.get('duration')
    if not isinstance(duration, (int,float)) or duration <= 0 or not valid:
        raise ProviderError('incomplete_video_metadata')
    return {'aweme_id':aid, 'url':'https://www.douyin.com/video/'+aid,
            'title':item.get('desc'), 'nickname':(item.get('author') or {}).get('nickname'),
            'source_duration_seconds':duration/1000,
            'source_duration_evidence':'Douyin_TikTok_Download_API aweme_detail.video.duration (ms)',
            'identity_evidence':'接口返回作品 ID 与请求作品 ID 一致；内容仍需审核',
            'video_download_url':valid[0], 'video_download_urls':valid,
            'rendition':{k:chosen.get(k) for k in ('width','height','data_size')}, 'metrics':item.get('statistics'),
            'create_time':item.get('create_time'), 'observed_at':now()}


async def fetch(project, aid, with_profile=False):
    if not (project/'crawlers/douyin/web/web_crawler.py').is_file():
        raise ProviderError('project_not_installed')
    logging.getLogger('Douyin_TikTok_Download_API_Crawlers').addHandler(logging.NullHandler())
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, str(project))
    from crawlers.douyin.web import web_crawler
    base = web_crawler.BaseCrawler
    class Bounded(base):
        def __init__(self,*args,**kwargs):
            kwargs.update(max_retries=1,max_connections=1,max_tasks=1,timeout=15)
            super().__init__(*args,**kwargs)

        async def get_fetch_data(self, url):
            # Keep the installed client's configured credentials inside the client.
            # Do not emit URLs, headers, cookies or platform response bodies.
            response = await self.aclient.get(url, follow_redirects=True)
            if response.status_code in (401,403,429):
                raise ProviderError('access_restricted')
            if response.status_code != 200:
                raise ProviderError('http_'+str(response.status_code))
            if not response.content.strip():
                raise ProviderError('empty_response')
            return response

        def parse_json(self, response):
            try:
                return response.json()
            except ValueError:
                raise ProviderError('non_json_response')
    web_crawler.BaseCrawler = Bounded
    client = web_crawler.DouyinWebCrawler()
    data = await asyncio.wait_for(client.fetch_one_video(aid),timeout=30)
    result = normalize(data, aid)
    author = data['aweme_detail'].get('author') or {}
    result['creator_id'] = str(author.get('uid') or '')
    result['sec_uid'] = author.get('sec_uid')
    if with_profile:
        if not result['sec_uid']:
            raise ProviderError('missing_creator_identity')
        profile = await asyncio.wait_for(client.handler_user_profile(result['sec_uid']),timeout=30)
        user = profile.get('user') if isinstance(profile,dict) else None
        if not isinstance(user,dict) or str(user.get('uid')) != result['creator_id']:
            raise ProviderError('creator_identity_mismatch')
        followers = user.get('follower_count')
        if not isinstance(followers,int) or followers < 0:
            raise ProviderError('followers_unavailable')
        result.update(follower_count=followers,total_favorited=user.get('total_favorited'),
            creator_metrics_observed_at=now(),creator_metrics_source='公开用户资料接口，与作品作者uid匹配',
            creator_url='https://www.douyin.com/user/'+result['sec_uid'])
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--id',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--with-profile',action='store_true',help='同时核实公开账号粉丝与总获赞')
    a=p.parse_args()
    if not a.id.isdigit() or not 10<=len(a.id)<=25:
        p.error('invalid work ID')
    if a.output.exists():p.error('output already exists; use a new version')
    try:
        result=asyncio.run(fetch(a.project.resolve(),a.id,a.with_profile))
        save(a.output,result)
        print(json.dumps({'status':'resolved','aweme_id':a.id,'duration_seconds':result['source_duration_seconds']}))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'failed','code':getattr(exc,'code',type(exc).__name__),
                          'hint':'空响应不是视频不存在；检查服务配置或上游兼容性，不自动重试、不标记完成'},ensure_ascii=False))
        return 2


if __name__=='__main__':sys.exit(main())
