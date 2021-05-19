"""Module to download a complete playlist from a youtube channel."""
import json
import logging
from collections.abc import Sequence
from datetime import date
from datetime import datetime
from typing import Dict, Tuple
from typing import Iterable
from typing import List
from typing import Optional
from typing import Union
from aiohttp import ClientSession
from async_property import async_property
from async_property import async_cached_property

from pytube import extract
from pytube import request
from pytube import YouTube
from pytube.helpers import cache
from pytube.helpers import install_proxy
from pytube.helpers import regex_search
from pytube.helpers import uniqueify

logger = logging.getLogger(__name__)


class Playlist:
    """Load a YouTube playlist with URL"""

    def __init__(self, url: str, proxies: Optional[Dict[str, str]] = None, session: ClientSession = None):
        if proxies:
            install_proxy(proxies)
        self._session = session if session else request.createSession()

        self._input_url = url

        # These need to be initialized as None for the properties.
        self._html = None
        self._ytcfg = None
        self._initial_data = None
        self._sidebar_info = None

        self._playlist_id = None

    @property
    def playlist_id(self):
        if self._playlist_id:
            return self._playlist_id
        self._playlist_id = extract.playlist_id(self._input_url)
        return self._playlist_id

    @property
    def playlist_url(self):
        return f"https://www.youtube.com/playlist?list={self.playlist_id}"

    @async_property
    async def html(self):
        if self._html:
            return self._html
        self._html = await request.get(self.playlist_url, self._session)
        return self._html

    @async_property
    async def ytcfg(self):
        if self._ytcfg:
            return self._ytcfg
        self._ytcfg = extract.get_ytcfg(await self.html)
        return self._ytcfg

    @async_property
    async def yt_api_key(self):
        return (await self.ytcfg)['INNERTUBE_API_KEY']
        
    @async_property
    async def initial_data(self):
        if self._initial_data:
            return self._initial_data
        else:
            self._initial_data = extract.initial_data(await self.html)
            return self._initial_data

    @async_property
    async def sidebar_info(self):
        if self._sidebar_info:
            return self._sidebar_info
        else:
            self._sidebar_info = (await self.initial_data)['sidebar'][
                'playlistSidebarRenderer']['items']
            return self._sidebar_info

    async def _paginate(
        self, until_watch_id: Optional[str] = None
    ) -> Iterable[List[str]]:
        """Parse the video links from the page source, yields the /watch?v=
        part from video link

        :param until_watch_id Optional[str]: YouTube Video watch id until
            which the playlist should be read.

        :rtype: Iterable[List[str]]
        :returns: Iterable of lists of YouTube watch ids
        """
        videos_urls, continuation = self._extract_videos(
            json.dumps(extract.initial_data(await self.html))
        )
        if until_watch_id:
            try:
                trim_index = videos_urls.index(f"/watch?v={until_watch_id}")
                yield videos_urls[:trim_index]
                return
            except ValueError:
                pass
        yield videos_urls

        # Extraction from a playlist only returns 100 videos at a time
        # if self._extract_videos returns a continuation there are more
        # than 100 songs inside a playlist, so we need to add further requests
        # to gather all of them
        if continuation:
            load_more_url, headers, data = await self._build_continuation_url(continuation)
        else:
            load_more_url, headers, data = None, None, None

        while load_more_url and headers and data:  # there is an url found
            logger.debug("load more url: %s", load_more_url)
            # requesting the next page of videos with the url generated from the
            # previous page, needs to be a post
            req = await request.post(load_more_url, self._session, extra_headers=headers, data=data)
            # extract up to 100 songs from the page loaded
            # returns another continuation if more videos are available
            videos_urls, continuation = self._extract_videos(req)
            if until_watch_id:
                try:
                    trim_index = videos_urls.index(f"/watch?v={until_watch_id}")
                    yield videos_urls[:trim_index]
                    return
                except ValueError:
                    pass
            yield videos_urls

            if continuation:
                load_more_url, headers, data = await self._build_continuation_url(
                    continuation
                )
            else:
                load_more_url, headers, data = None, None, None

    async def _build_continuation_url(self, continuation: str) -> Tuple[str, dict, dict]:
        """Helper method to build the url and headers required to request
        the next page of videos

        :param str continuation: Continuation extracted from the json response
            of the last page
        :rtype: Tuple[str, dict, dict]
        :returns: Tuple of an url and required headers for the next http
            request
        """
        return (
            (
                # was changed to this format (and post requests)
                # between 2021.03.02 and 2021.03.03
                "https://www.youtube.com/youtubei/v1/browse?key="
                f"{await self.yt_api_key}"
            ),
            {
                "X-YouTube-Client-Name": "1",
                "X-YouTube-Client-Version": "2.20200720.00.02",
                "X-Origin": "https://www.youtube.com"
            },
            # extra data required for post request
            {
                "continuation": continuation,
                "context": {
                    "client": {
                        "clientName": "WEB",
                        "clientVersion": "2.20200720.00.02"
                    }
                }
            }
        )

    @staticmethod
    def _extract_videos(raw_json: str) -> Tuple[List[str], Optional[str]]:
        """Extracts videos from a raw json page

        :param str raw_json: Input json extracted from the page or the last
            server response
        :rtype: Tuple[List[str], Optional[str]]
        :returns: Tuple containing a list of up to 100 video watch ids and
            a continuation token, if more videos are available
        """
        initial_data = json.loads(raw_json)
        try:
            # this is the json tree structure, if the json was extracted from
            # html
            section_contents = initial_data["contents"][
                "twoColumnBrowseResultsRenderer"][
                "tabs"][0]["tabRenderer"]["content"][
                "sectionListRenderer"]["contents"]
            try:
                # Playlist without submenus
                important_content = section_contents[
                    0]["itemSectionRenderer"][
                    "contents"][0]["playlistVideoListRenderer"]
            except (KeyError, IndexError, TypeError):
                # Playlist with submenus
                important_content = section_contents[
                    1]["itemSectionRenderer"][
                    "contents"][0]["playlistVideoListRenderer"]
            videos = important_content["contents"]
        except (KeyError, IndexError, TypeError):
            try:
                # this is the json tree structure, if the json was directly sent
                # by the server in a continuation response
                # no longer a list and no longer has the "response" key
                important_content = initial_data['onResponseReceivedActions'][0][
                    'appendContinuationItemsAction']['continuationItems']
                videos = important_content
            except (KeyError, IndexError, TypeError) as p:
                logger.info(p)
                return [], None

        try:
            continuation = videos[-1]['continuationItemRenderer'][
                'continuationEndpoint'
            ]['continuationCommand']['token']
            videos = videos[:-1]
        except (KeyError, IndexError):
            # if there is an error, no continuation is available
            continuation = None

        # remove duplicates
        return (
            uniqueify(
                list(
                    # only extract the video ids from the video data
                    map(
                        lambda x: (
                            f"/watch?v="
                            f"{x['playlistVideoRenderer']['videoId']}"
                        ),
                        videos
                    )
                ),
            ),
            continuation,
        )

    async def trimmed(self, video_id: str) -> Iterable[str]:
        """Retrieve a list of YouTube video URLs trimmed at the given video ID

        i.e. if the playlist has video IDs 1,2,3,4 calling trimmed(3) returns
        [1,2]
        :type video_id: str
            video ID to trim the returned list of playlist URLs at
        :rtype: List[str]
        :returns:
            List of video URLs from the playlist trimmed at the given ID
        """
        for page in await self._paginate(until_watch_id=video_id):
            yield (self._video_url(watch_path) for watch_path in page)

    # @async_cached_property  # type: ignore
    # async def video_urls(self) -> List[str]:
    #     """Complete links of all the videos in playlist

    #     :rtype: List[str]
    #     :returns: List of video URLs
    #     """
    #     return [
    #         self._video_url(video)
    #         async for page in await self._paginate()
    #         for video in page
    #     ]

    async def video_urls(self) -> Iterable[str]:
        async for page in self._paginate():
            for vid in page:
                yield self._video_url(vid)

    async def videos(self) -> Iterable[YouTube]:
        """Yields YouTube objects of videos in this playlist

        :rtype: List[YouTube]
        :returns: List of YouTube
        """
        yield (YouTube(url) for url in await self.video_urls)

    # def __getitem__(self, i: Union[slice, int]) -> Union[str, List[str]]:
    #     return self.video_urls[i]

    # def __len__(self) -> int:
    #     return len(self.video_urls)

    # def __repr__(self) -> str:
    #     return f"{self.video_urls}"

    @async_cached_property
    async def last_updated(self) -> Optional[date]:
        date_match = re.search(
            r"Last updated on (\w{3}) (\d{1,2}), (\d{4})", await self.html
        )
        if date_match:
            month, day, year = date_match.groups()
            return datetime.strptime(
                f"{month} {day:0>2} {year}", "%b %d %Y"
            ).date()
        return None

    @async_cached_property
    async def title(self) -> Optional[str]:
        """Extract playlist title

        :return: playlist title (name)
        :rtype: Optional[str]
        """
        pattern = r"<title>(.+?)</title>"
        # return regex_search(pattern, await self.html, 1).replace("- YouTube", "").strip()
        return (await self.sidebar_info)[0]['playlistSidebarPrimaryInfoRenderer'][
            'title']['runs'][0]['text']

    @async_property
    async def description(self) -> str:
        return (await self.sidebar_info)[0]['playlistSidebarPrimaryInfoRenderer'][
            'description']['simpleText']

    @async_property
    async def length(self):
        """Extract the number of videos in the playlist.

        :return: Playlist video count
        :rtype: int
        """
        count_text = (await self.sidebar_info)[0]['playlistSidebarPrimaryInfoRenderer'][
            'stats'][0]['runs'][0]['text']
        return int(count_text)

    @async_property
    async def views(self):
        """Extract view count for playlist.

        :return: Playlist view count
        :rtype: int
        """
        # "1,234,567 views"
        views_text = (await self.sidebar_info)[0]['playlistSidebarPrimaryInfoRenderer'][
            'stats'][1]['simpleText']
        # "1,234,567"
        count_text = views_text.split()[0]
        # "1234567"
        count_text = count_text.replace(',', '')
        return int(count_text)

    @async_property
    async def owner(self):
        """Extract the owner of the playlist.

        :return: Playlist owner name.
        :rtype: str
        """
        return (await self.sidebar_info)[1]['playlistSidebarSecondaryInfoRenderer'][
            'videoOwner']['videoOwnerRenderer']['title']['runs'][0]['text']

    @async_property
    async def owner_id(self):
        """Extract the channel_id of the owner of the playlist.

        :return: Playlist owner's channel ID.
        :rtype: str
        """
        return (await self.sidebar_info)[1]['playlistSidebarSecondaryInfoRenderer'][
            'videoOwner']['videoOwnerRenderer']['title']['runs'][0][
            'navigationEndpoint']['browseEndpoint']['browseId']

    @async_property
    async def owner_url(self):
        """Create the channel url of the owner of the playlist.

        :return: Playlist owner's channel url.
        :rtype: str
        """
        return f'https://www.youtube.com/channel/{(await self.owner_id)}'

    @staticmethod
    def _video_url(watch_path: str):
        return f"https://www.youtube.com{watch_path}"
