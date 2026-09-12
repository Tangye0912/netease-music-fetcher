from unittest import mock

import pytest

from music_fetch.api import DownloadCanceled, PlayableCandidate
from music_fetch.pipeline import run_download_pipeline


def source(**kwargs):
    kwargs["output_path"].write_bytes(b"new-audio")
    return PlayableCandidate("https://example.invalid/song.flac", 0, "lossless", "flac")


def test_source_fallback_keeps_tags_and_lyrics(tmp_path):
    stages = []
    with mock.patch("music_fetch.pipeline.download_song_with_fallback", side_effect=source), \
            mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=False), \
            mock.patch("music_fetch.pipeline.write_audio_tags") as tags, \
            mock.patch("music_fetch.api.fetch_lyric", return_value=mock.Mock(lyric="[00:01]original", translated_lyric="")) as lyric, \
            mock.patch("music_fetch.audio.embed_lyric_tag"):
        result = run_download_pipeline(song_id="1", cookie="", output_path=tmp_path / "song.mp3",
                                       tags={"title": "Song"}, download_lyric=True, stage_callback=stages.append)
    assert result.output_path.suffix == ".flac"
    tags.assert_called_once()
    lyric.assert_called_once()
    assert result.output_path.with_suffix(".lrc").read_text().endswith("original")
    assert stages[-1] == "finishing"
    assert not list(tmp_path.glob(".music-fetch-*"))


def test_cancel_never_deletes_existing_files(tmp_path):
    target = tmp_path / "song.mp3"
    target.write_bytes(b"existing")
    with pytest.raises(DownloadCanceled):
        run_download_pipeline(song_id="1", cookie="", output_path=target, cancel_checker=lambda: True)
    assert target.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".music-fetch-*"))


def test_fallback_race_uses_another_name(tmp_path):
    target = tmp_path / "song.flac"
    target.write_bytes(b"existing")
    with mock.patch("music_fetch.pipeline.download_song_with_fallback", side_effect=source), \
            mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=False):
        result = run_download_pipeline(song_id="1", cookie="", output_path=tmp_path / "song.mp3")
    assert result.output_path != target
    assert target.read_bytes() == b"existing"
    assert result.output_path.read_bytes() == b"new-audio"


def test_conversion_cancel_terminates_child():
    from music_fetch.audio import _run_cancelable_conversion
    child = mock.Mock()
    child.poll.return_value = None
    with mock.patch("music_fetch.audio.subprocess.Popen", return_value=child):
        with pytest.raises(DownloadCanceled):
            _run_cancelable_conversion(["ffmpeg"], 20, mock.Mock(side_effect=[False, True]))
    child.terminate.assert_called_once()
    child.communicate.assert_called_once_with(timeout=2)
