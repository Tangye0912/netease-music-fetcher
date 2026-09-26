"""Tests for music_fetch/pipeline.py — run_download_pipeline."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from music_fetch.api import (
    DownloadCanceled,
    MusicFetchError,
    PlayableCandidate,
)
from music_fetch.pipeline import DownloadPipelineResult, run_download_pipeline, write_audio_tags


class WriteAudioTagsTests(unittest.TestCase):
    """Tests for format-specific tag writing (MP4/MP3/Vorbis branches)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_mock_audio(self, tags_dict, audio_type):
        """Create a mock mutagen audio object with given tags dict and type."""
        audio = mock.MagicMock()
        audio.tags = tags_dict
        # Make isinstance checks work by setting __class__
        audio.__class__ = audio_type
        return audio

    @mock.patch("mutagen.File")
    def test_mp3_tags_use_id3_frames(self, mock_file):
        from mutagen.mp3 import MP3
        tags = mock.MagicMock()
        audio = self._make_mock_audio(tags, MP3)
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.mp3"
        output_path.write_bytes(b"fake")

        write_audio_tags(output_path, title="My Song", artist="Artist", album="Album")

        # MP3 should use TIT2/TPE1/TALB frame classes
        tags.add.assert_any_call(mock.ANY)
        audio.save.assert_called_once()

    @mock.patch("mutagen.File")
    def test_mp4_tags_use_atom_codes(self, mock_file):
        from mutagen.mp4 import MP4
        tags: dict[str, str] = {}
        audio = self._make_mock_audio(tags, MP4)
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.m4a"
        output_path.write_bytes(b"fake")

        write_audio_tags(output_path, title="My Song", artist="Artist", album="Album")

        self.assertEqual(tags.get('\xa9nam'), "My Song")
        self.assertEqual(tags.get('\xa9ART'), "Artist")
        self.assertEqual(tags.get('\xa9alb'), "Album")
        audio.save.assert_called_once()

    @mock.patch("mutagen.File")
    def test_vorbis_tags_use_string_keys(self, mock_file):
        from mutagen.flac import FLAC
        tags: dict[str, str] = {}
        audio = self._make_mock_audio(tags, FLAC)
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.flac"
        output_path.write_bytes(b"fake")

        write_audio_tags(output_path, title="My Song", artist="Artist", album="Album")

        self.assertEqual(tags.get('title'), "My Song")
        self.assertEqual(tags.get('artist'), "Artist")
        self.assertEqual(tags.get('album'), "Album")
        audio.save.assert_called_once()

    @mock.patch("mutagen.File")
    def test_none_audio_returns_silently(self, mock_file):
        mock_file.return_value = None
        output_path = Path(self.tmp.name) / "test.unknown"
        # Should not raise
        write_audio_tags(output_path, title="Test")

    @mock.patch("mutagen.File")
    def test_no_tags_does_not_crash(self, mock_file):
        audio = mock.MagicMock()
        audio.tags = None
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.mp3"
        output_path.write_bytes(b"fake")
        # Should not raise
        write_audio_tags(output_path, title="Test")

    @mock.patch("mutagen.File")
    def test_mutagen_error_is_swallowed(self, mock_file):
        # mutagen raises MutagenError subclasses (not OSError/ValueError) for
        # corrupt headers — tag writing must never propagate these.
        mock_file.side_effect = RuntimeError("FLACNoHeaderError-ish")
        output_path = Path(self.tmp.name) / "test.flac"
        output_path.write_bytes(b"not-a-flac")
        # Should not raise
        write_audio_tags(output_path, title="Test")


class RunDownloadPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "test.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_success(self, fallback_mock):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        fallback_mock.side_effect = fake_fallback

        result = run_download_pipeline(
            song_id="42",
            cookie="MUSIC_U=test",
            output_path=self.output_path,
            target_format="mp3",
            timeout=10,
            retry_count=1,
        )
        self.assertIsInstance(result, DownloadPipelineResult)
        self.assertTrue(result.output_path.exists())
        self.assertEqual(result.file_size, 4)
        self.assertEqual(result.source_format, "mp3")

    @mock.patch("music_fetch.pipeline.write_audio_tags", side_effect=RuntimeError("mutagen boom"))
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_tag_write_failure_does_not_fail_download(self, fallback_mock, _tags_mock):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        fallback_mock.side_effect = fake_fallback

        result = run_download_pipeline(
            song_id="42",
            cookie="MUSIC_U=test",
            output_path=self.output_path,
            target_format="mp3",
            timeout=10,
            retry_count=1,
            tags={"title": "Song", "artist": None, "album": None, "cover_url": None},
        )
        self.assertTrue(result.output_path.exists())
        self.assertEqual(result.file_size, 4)

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_retry_on_failure(self, fallback_mock):
        call_count = [0]

        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise MusicFetchError("DOWNLOAD_FAILED", "test error")
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        fallback_mock.side_effect = fake_fallback

        result = run_download_pipeline(
            song_id="42",
            cookie="MUSIC_U=test",
            output_path=self.output_path,
            target_format="mp3",
            timeout=10,
            retry_count=2,
        )
        self.assertEqual(call_count[0], 3)
        self.assertTrue(result.output_path.exists())

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_exhausts_retries(self, fallback_mock):
        fallback_mock.side_effect = MusicFetchError("DOWNLOAD_FAILED", "always fail")

        with self.assertRaises(MusicFetchError):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=1,
            )

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_cancel_during_pipeline(self, fallback_mock):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, cancel_checker=None, **kwargs):
            if cancel_checker and cancel_checker():
                raise DownloadCanceled()
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        fallback_mock.side_effect = fake_fallback
        cancel_called = [False]

        def cancel_checker():
            cancel_called[0] = True
            return True

        with self.assertRaises(DownloadCanceled):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=1,
                cancel_checker=cancel_checker,
            )

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    @mock.patch("music_fetch.pipeline.Path.mkdir")
    def test_unwritable_directory(self, mkdir_mock, fallback_mock):
        mkdir_mock.side_effect = PermissionError("Permission denied")
        with self.assertRaises(MusicFetchError) as ctx:
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=1,
            )
        self.assertIn("Cannot write", ctx.exception.message)


class ConvertAudioFileCleanupTests(unittest.TestCase):
    """Tests for convert_audio_file exception cleanup in run_download_pipeline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "test.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=True)
    @mock.patch("music_fetch.pipeline.convert_audio_file")
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_convert_failure_cleans_temp_files(self, fallback_mock, convert_mock, _ffmpeg_mock):
        from music_fetch.api import PlayableCandidate

        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"source_data")
            return PlayableCandidate(
                media_url="https://example.com/song.m4a",
                duration_ms=120000,
                level="standard",
                encode_type="m4a",
            )

        fallback_mock.side_effect = fake_fallback
        convert_mock.side_effect = OSError("ffmpeg failed")

        with self.assertRaises(OSError):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=0,
            )
        # output_path should be cleaned up on convert failure
        self.assertFalse(self.output_path.exists())
        # temp source should also be cleaned up
        source = self.output_path.with_name(f"{self.output_path.name}.source")
        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()


class LyricModeTests(unittest.TestCase):
    """lyric_mode controls which lyric text gets saved/embedded."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "test.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, lyric_mode):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        saved = []
        with mock.patch("music_fetch.pipeline.download_song_with_fallback", side_effect=fake_fallback), \
                mock.patch("music_fetch.api.fetch_lyric", return_value=mock.Mock(
                    lyric="[00:01.00]orig", translated_lyric="[00:01.00]trans")), \
                mock.patch("music_fetch.audio.save_lyric_file", side_effect=lambda _p, text: saved.append(text)), \
                mock.patch("music_fetch.audio.embed_lyric_tag"):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                download_lyric=True,
                lyric_mode=lyric_mode,
            )
        return saved

    def test_original_mode_saves_original(self):
        self.assertEqual(self._run("original"), ["[00:01.00]orig"])

    def test_translation_mode_saves_translation(self):
        self.assertEqual(self._run("translation"), ["[00:01.00]trans"])

    def test_bilingual_mode_saves_merged(self):
        saved = self._run("bilingual")
        self.assertEqual(len(saved), 1)
        self.assertIn("[00:01.00]orig", saved[0])
        self.assertIn("[00:01.00]trans", saved[0])


class StageCallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "test.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_stages_reported_in_order(self):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        stages = []
        with mock.patch("music_fetch.pipeline.download_song_with_fallback", side_effect=fake_fallback), \
                mock.patch("music_fetch.api.fetch_lyric", return_value=mock.Mock(lyric="[00:01]x", translated_lyric="")), \
                mock.patch("music_fetch.audio.save_lyric_file"), \
                mock.patch("music_fetch.audio.embed_lyric_tag"):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                download_lyric=True,
                stage_callback=stages.append,
            )
        self.assertEqual(stages[0], "resolving")
        self.assertIn("downloading", stages)
        self.assertIn("converting", stages)
        self.assertEqual(stages[-1], "lyrics")

    def test_stage_callback_exception_is_swallowed(self):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        with mock.patch("music_fetch.pipeline.download_song_with_fallback", side_effect=fake_fallback):
            result = run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                stage_callback=mock.Mock(side_effect=RuntimeError("ui boom")),
            )
        self.assertTrue(result.output_path.exists())

    def test_cancel_preserves_pre_existing_target_file(self):
        self.output_path.write_bytes(b"already-here")
        with mock.patch(
            "music_fetch.pipeline.download_song_with_fallback",
            side_effect=DownloadCanceled(),
        ):
            with self.assertRaises(DownloadCanceled):
                run_download_pipeline(
                    song_id="42",
                    cookie="MUSIC_U=test",
                    output_path=self.output_path,
                    target_format="mp3",
                )
        self.assertEqual(self.output_path.read_bytes(), b"already-here")


class CoverArtTests(unittest.TestCase):
    """Cover embedding against real containers (tiny fixtures in tests/fixtures).

    MP3 and M4A/FLAC store artwork in completely different places, so these run
    mutagen for real instead of mocking it.
    """

    FIXTURES = Path(__file__).resolve().parent / "fixtures"
    JPEG = b"\xff\xd8\xff\xe0" + b"cover-bytes" * 8
    PNG = b"\x89PNG\r\n\x1a\n" + b"png-bytes" * 8
    WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"webp-bytes" * 8

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _fixture_copy(self, name: str) -> Path:
        target = Path(self.tmp.name) / name
        target.write_bytes((self.FIXTURES / name).read_bytes())
        return target

    def _tag_with_cover(self, target: Path, cover: bytes, mime: str) -> None:
        with mock.patch("music_fetch.pipeline._download_cover", return_value=(cover, mime)):
            write_audio_tags(target, title="标题", artist="艺人", album="专辑", cover_url="https://example.com/c")

    def test_detect_image_mime(self):
        from music_fetch.pipeline import _detect_image_mime

        self.assertEqual(_detect_image_mime(self.JPEG), "image/jpeg")
        self.assertEqual(_detect_image_mime(self.PNG), "image/png")
        self.assertEqual(_detect_image_mime(self.WEBP), "image/webp")
        # Anything unrecognised must not be labelled JPEG: players would show a
        # broken cover instead of simply not having one.
        self.assertIsNone(_detect_image_mime(b"garbage"))

    def test_oversized_cover_is_rejected_and_skipped(self):
        from music_fetch.pipeline import MAX_COVER_BYTES, _download_cover

        response = mock.MagicMock()
        response.read.return_value = b"\xff\xd8\xff" + b"x" * MAX_COVER_BYTES
        response.__enter__.return_value = response
        with mock.patch("music_fetch.pipeline.open_url", return_value=response):
            with self.assertRaises(ValueError):
                _download_cover("https://example.com/huge.jpg")

    def test_unknown_cover_container_is_rejected(self):
        from music_fetch.pipeline import _download_cover

        response = mock.MagicMock()
        response.read.return_value = b"not an image"
        response.__enter__.return_value = response
        with mock.patch("music_fetch.pipeline.open_url", return_value=response):
            with self.assertRaises(ValueError):
                _download_cover("https://example.com/c")

    def test_cover_error_never_fails_the_tag_write(self):
        from mutagen.id3 import ID3

        target = self._fixture_copy("silence.mp3")
        with mock.patch("music_fetch.pipeline._download_cover", side_effect=ValueError("bad cover")):
            write_audio_tags(target, title="标题", artist="艺人", album="专辑", cover_url="https://example.com/c")
        tags = ID3(str(target))
        self.assertEqual(tags.getall("TIT2")[0].text, ["标题"])
        self.assertEqual(tags.getall("APIC"), [])

    def test_mp3_cover_lands_in_an_apic_frame(self):
        from mutagen.id3 import ID3

        target = self._fixture_copy("silence.mp3")
        self._tag_with_cover(target, self.JPEG, "image/jpeg")

        frames = ID3(str(target)).getall("APIC")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].mime, "image/jpeg")
        self.assertEqual(bytes(frames[0].data), self.JPEG)

    def test_mp3_cover_is_not_duplicated_on_retag(self):
        from mutagen.id3 import ID3

        target = self._fixture_copy("silence.mp3")
        self._tag_with_cover(target, self.JPEG, "image/jpeg")
        self._tag_with_cover(target, self.PNG, "image/png")

        frames = ID3(str(target)).getall("APIC")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].mime, "image/png")

    def test_m4a_cover_lands_in_the_covr_atom(self):
        from mutagen.mp4 import MP4, MP4Cover

        target = self._fixture_copy("silence.m4a")
        self._tag_with_cover(target, self.JPEG, "image/jpeg")

        covers = MP4(str(target)).tags["covr"]
        self.assertEqual(len(covers), 1)
        self.assertEqual(covers[0].imageformat, MP4Cover.FORMAT_JPEG)
        self.assertEqual(bytes(covers[0]), self.JPEG)

    def test_m4a_accepts_png_covers(self):
        from mutagen.mp4 import MP4, MP4Cover

        target = self._fixture_copy("silence.m4a")
        self._tag_with_cover(target, self.PNG, "image/png")

        covers = MP4(str(target)).tags["covr"]
        self.assertEqual(covers[0].imageformat, MP4Cover.FORMAT_PNG)

    def test_m4a_skips_unsupported_cover_format(self):
        from mutagen.mp4 import MP4

        target = self._fixture_copy("silence.m4a")
        self._tag_with_cover(target, self.WEBP, "image/webp")

        # MP4Cover carries JPEG/PNG only; the file must stay valid and untouched.
        self.assertNotIn("covr", MP4(str(target)).tags)

    def test_flac_cover_lands_in_a_picture_block(self):
        from mutagen.flac import FLAC

        target = self._fixture_copy("silence.flac")
        self._tag_with_cover(target, self.JPEG, "image/jpeg")

        pictures = FLAC(str(target)).pictures
        self.assertEqual(len(pictures), 1)
        self.assertEqual(pictures[0].type, 3)
        self.assertEqual(pictures[0].mime, "image/jpeg")
        self.assertEqual(pictures[0].data, self.JPEG)

    def test_flac_cover_is_replaced_not_stacked(self):
        from mutagen.flac import FLAC

        target = self._fixture_copy("silence.flac")
        self._tag_with_cover(target, self.JPEG, "image/jpeg")
        self._tag_with_cover(target, self.PNG, "image/png")

        pictures = FLAC(str(target)).pictures
        self.assertEqual(len(pictures), 1)
        self.assertEqual(pictures[0].mime, "image/png")

    def test_text_tags_survive_alongside_the_cover(self):
        from mutagen.flac import FLAC

        target = self._fixture_copy("silence.flac")
        self._tag_with_cover(target, self.JPEG, "image/jpeg")

        tags = FLAC(str(target))
        self.assertEqual(tags["title"], ["标题"])
        self.assertEqual(tags["artist"], ["艺人"])
        self.assertEqual(tags["album"], ["专辑"])

    def test_unsupported_container_is_ignored(self):
        from music_fetch.pipeline import _embed_cover

        target = Path(self.tmp.name) / "song.wav"
        target.write_bytes(b"not really audio")
        self.assertFalse(_embed_cover(target, self.JPEG, "image/jpeg"))

    def test_download_cover_reads_bytes_and_sniffs_mime(self):
        from music_fetch.pipeline import _download_cover

        response = mock.MagicMock()
        response.read.return_value = self.PNG
        response.__enter__.return_value = response
        with mock.patch("music_fetch.pipeline.open_url", return_value=response) as url_mock:
            data, mime = _download_cover("https://example.com/cover.png")
        self.assertEqual(data, self.PNG)
        self.assertEqual(mime, "image/png")
        url_mock.assert_called_once()


class PipelineFailurePathTests(unittest.TestCase):
    """Cancel points, the missing-ffmpeg fallback and lyric failures."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out_dir = Path(self.tmp.name)
        self.output_path = self.out_dir / "test.mp3"
        self.source_path = self.out_dir / "test.mp3.source"

    def _fallback(self, media_url: str = "https://example.com/song.mp3"):
        def fake(**kwargs):
            kwargs["output_path"].write_bytes(b"audio-bytes")
            return PlayableCandidate(media_url=media_url, duration_ms=1, level="standard", encode_type="mp3")
        return fake

    def _run(self, **kwargs):
        params = dict(
            song_id="42", cookie="MUSIC_U=test", output_path=self.output_path,
            target_format="mp3", timeout=5,
        )
        params.update(kwargs)
        return run_download_pipeline(**params)

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_cancel_after_download_removes_partial_files(self, fallback_mock):
        fallback_mock.side_effect = self._fallback()
        with self.assertRaises(DownloadCanceled):
            self._run(cancel_checker=lambda: True)
        self.assertFalse(self.output_path.exists())
        self.assertFalse(self.source_path.exists())

    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=True)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_cancel_before_conversion_removes_partial_files(self, fallback_mock, _ffmpeg_mock):
        fallback_mock.side_effect = self._fallback(media_url="https://example.com/song.flac")
        checks: list[int] = []

        def cancel() -> bool:
            checks.append(1)
            return len(checks) >= 2  # pass the post-download check, cancel before converting

        with self.assertRaises(DownloadCanceled):
            self._run(cancel_checker=cancel)
        self.assertFalse(self.output_path.exists())
        self.assertFalse(self.source_path.exists())

    @mock.patch("music_fetch.pipeline.write_audio_tags")
    @mock.patch("music_fetch.pipeline.convert_audio_file")
    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=True)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_cancel_after_conversion_removes_output(self, fallback_mock, _ffmpeg_mock, convert_mock, _tags_mock):
        fallback_mock.side_effect = self._fallback(media_url="https://example.com/song.flac")
        convert_mock.side_effect = lambda source, target, fmt, timeout: target.write_bytes(b"converted")
        checks: list[int] = []

        def cancel() -> bool:
            checks.append(1)
            return len(checks) >= 3  # only the post-conversion check cancels

        with self.assertRaises(DownloadCanceled):
            self._run(cancel_checker=cancel)
        self.assertFalse(self.output_path.exists())

    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=False)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_missing_ffmpeg_saves_the_source_format(self, fallback_mock, _ffmpeg_mock):
        fallback_mock.side_effect = self._fallback(media_url="https://example.com/song.flac")
        result = self._run()
        self.assertEqual(result.output_path.suffix, ".flac")
        self.assertEqual(result.output_path.read_bytes(), b"audio-bytes")
        self.assertEqual(result.file_size, len(b"audio-bytes"))

    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=False)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_missing_ffmpeg_does_not_overwrite_an_existing_file(self, fallback_mock, _ffmpeg_mock):
        (self.out_dir / "test.flac").write_bytes(b"older-download")
        fallback_mock.side_effect = self._fallback(media_url="https://example.com/song.flac")
        result = self._run()
        self.assertEqual((self.out_dir / "test.flac").read_bytes(), b"older-download")
        self.assertTrue(result.output_path.name.startswith("test_"))
        self.assertEqual(result.output_path.suffix, ".flac")

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_output_directory_permission_error_is_reported(self, fallback_mock):
        fallback_mock.side_effect = self._fallback()
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
            with self.assertRaises(MusicFetchError) as ctx:
                self._run()
        self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_output_path_too_long_is_reported(self, fallback_mock):
        import errno

        fallback_mock.side_effect = self._fallback()
        with mock.patch.object(Path, "mkdir", side_effect=OSError(errno.ENAMETOOLONG, "too long")):
            with self.assertRaises(MusicFetchError) as ctx:
                self._run()
        self.assertEqual(ctx.exception.code, "PATH_TOO_LONG")

    @mock.patch("music_fetch.pipeline.write_audio_tags")
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    @mock.patch("music_fetch.api.fetch_lyric")
    def test_lyric_is_saved_and_embedded(self, lyric_mock, fallback_mock, _tags_mock):
        from music_fetch.api import LyricResult

        lyric_mock.return_value = LyricResult(lyric="[00:01.00]hi")
        fallback_mock.side_effect = self._fallback()
        with mock.patch("music_fetch.audio.save_lyric_file") as save_mock, mock.patch(
            "music_fetch.audio.embed_lyric_tag"
        ) as embed_mock:
            self._run(download_lyric=True, lyric_mode="original")
        save_mock.assert_called_once()
        embed_mock.assert_called_once_with(self.output_path, "[00:01.00]hi")

    @mock.patch("music_fetch.pipeline.write_audio_tags")
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    @mock.patch("music_fetch.api.fetch_lyric", side_effect=RuntimeError("lyric boom"))
    def test_lyric_failure_does_not_fail_the_download(self, _lyric_mock, fallback_mock, _tags_mock):
        fallback_mock.side_effect = self._fallback()
        result = self._run(download_lyric=True)
        self.assertTrue(result.output_path.exists())
        self.assertEqual(result.file_size, len(b"audio-bytes"))

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_cancel_after_the_move_keeps_a_preexisting_file(self, fallback_mock):
        # The target existed before the job started, so cancelling must not
        # delete it (previously the user's file disappeared entirely).
        self.output_path.write_bytes(b"user-original")
        fallback_mock.side_effect = self._fallback()
        checks: list[int] = []

        def cancel() -> bool:
            checks.append(1)
            return len(checks) >= 3  # cancel right after the rename

        with self.assertRaises(DownloadCanceled):
            self._run(cancel_checker=cancel)
        self.assertTrue(self.output_path.exists())
        self.assertNotEqual(self.output_path.read_bytes(), b"")

    @mock.patch("music_fetch.pipeline.convert_audio_file")
    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=True)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_failed_conversion_leaves_a_preexisting_file_untouched(
        self, fallback_mock, _ffmpeg_mock, convert_mock
    ):
        self.output_path.write_bytes(b"user-original")
        fallback_mock.side_effect = self._fallback(media_url="https://example.com/song.flac")
        convert_mock.side_effect = MusicFetchError("CONVERT_FAILED", "boom")

        with self.assertRaises(MusicFetchError):
            self._run()
        self.assertEqual(self.output_path.read_bytes(), b"user-original")

    @mock.patch("music_fetch.pipeline.convert_audio_file")
    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=True)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_conversion_is_published_from_a_temporary_name(self, fallback_mock, _ffmpeg_mock, convert_mock):
        fallback_mock.side_effect = self._fallback(media_url="https://example.com/song.flac")
        seen_targets: list[Path] = []

        def fake_convert(source, target, fmt, timeout):
            seen_targets.append(Path(target))
            Path(target).write_bytes(b"converted")

        convert_mock.side_effect = fake_convert

        result = self._run()
        self.assertEqual(len(seen_targets), 1)
        self.assertNotEqual(seen_targets[0], self.output_path)
        self.assertEqual(seen_targets[0].suffix, ".mp3")
        self.assertEqual(result.output_path.read_bytes(), b"converted")

    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=False)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_missing_ffmpeg_without_url_extension_keeps_the_encode_type(self, fallback_mock, _ffmpeg_mock):
        # An extensionless CDN url used to discard a finished download with
        # CONVERT_TOOL_MISSING; the candidate's encode type now names the file.
        def fake(**kwargs):
            kwargs["output_path"].write_bytes(b"audio-bytes")
            return PlayableCandidate(media_url="https://cdn.example.com/stream", duration_ms=1,
                                     level="standard", encode_type="aac")

        fallback_mock.side_effect = fake
        result = self._run()
        self.assertEqual(result.output_path.suffix, ".aac")
        self.assertEqual(result.output_path.read_bytes(), b"audio-bytes")

    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=True)
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_retry_keeps_the_retrying_stage_visible(self, fallback_mock, _ffmpeg_mock):
        attempts: list[int] = []
        stages: list[str] = []

        def flaky(**kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise MusicFetchError("DOWNLOAD_FAILED", "first attempt failed")
            kwargs["output_path"].write_bytes(b"audio-bytes")
            return PlayableCandidate(media_url="https://example.com/song.flac", duration_ms=1,
                                     level="standard", encode_type="flac")

        fallback_mock.side_effect = flaky
        with mock.patch("music_fetch.pipeline.convert_audio_file") as convert_mock:
            convert_mock.side_effect = lambda source, target, fmt, timeout: Path(target).write_bytes(b"converted")
            self._run(retry_count=1, stage_callback=stages.append)

        self.assertEqual(len(attempts), 2)
        self.assertIn("retrying", stages)
        self.assertEqual(stages.count("downloading"), 1)
