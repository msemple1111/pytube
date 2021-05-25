<div align="center">
  <p>
    <a href="#"><img src="https://assets.nickficano.com/gh-pytube.min.svg" width="456" height="143" alt="pytube logo" /></a>
  </p>
  <p align="center">
	<a href="https://pypi.org/project/pytube-async/"><img src="https://img.shields.io/pypi/dm/pytube?style=flat-square" alt="pypi"/></a>
	<a href="https://pypi.org/project/pytube-async/"><img src="https://img.shields.io/pypi/v/pytube?style=flat-square" /></a>
  </p>
</div>

### Actively soliciting contributers!

Have ideas for how *pytube async* can be improved? Feel free to open an issue or a pull
request!

# pytube

*pytube async* is a fork of pytube - [pytube.io](https://pytube.io) 
Note: this is not actively maintained, only occasionally 

## Documentation

The code is the Documentation...

Pytube Async's parent's documentation is useful and can be found on 
[pytube.io](https://pytube.io). 

Note: almost every property/method is an async method.


### Installation

Pytube requires an installation of python 3.6 or greater, as well as pip.
Pip is typically bundled with python installations, and you can find options
for how to install python at https://python.org.

Note: i will put this on pypy sometime soonish

To install from source with pip:

```bash
$ python -m pip install git+https://github.com/msemple1111/pytube
```

on windows, open cmd.exe and run:
```bash
py -m pip install git+https://github.com/msemple1111/pytube
```

## Description

Note: this is not maintained as much as the parent project, only when things break - open an issue if you find a bug.

YouTube is the most popular video-sharing platform in the world and as a hacker
you may encounter a situation where you want to script something to download
videos. For this I present to you *pytube async*.

*pytube async* is a lightweight library written in Python. It has no third party
dependencies and aims to be highly reliable.

*pytube async* also makes pipelining easy, allowing you to specify callback functions
for different download events, such as  ``on progress`` or ``on complete``.

## Features

- asyncio support!!
- Support for both progressive & DASH streams
- Support for downloading complete playlists
- Easily register ``on_download_progress`` & ``on_download_complete`` callbacks
- Command-line interfaced included
- Caption track support
- Outputs caption tracks to .srt format (SubRip Subtitle)
- Ability to capture thumbnail URL
- Extensively documented source code
- No third-party dependencies

## Quickstart

This guide is only meant to cover the most basic usage of the library.


### Using pytube in a python script

To download a video using the library in a script, you'll need to first import
the YouTube class from the library, and pass it an argument of the video url.
From there, you can access the streams and download them.
Note: async code needs to run inside the event loop

```python
 >>> from pytube import YouTube
 >>> yt = YouTube('https://youtu.be/2lAe1cqCOXo')
 >>> streams = await yt.streams
 >>> video = streams.filter(progressive=True, file_extension='mp4').first()
 >>> await video.download()
```
