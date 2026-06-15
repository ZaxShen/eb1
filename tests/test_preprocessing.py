"""Unit tests for pipeline.segmentation.preprocessing."""

import pytest

from pipeline.segmentation.preprocessing import (
    _clean_user_upload,
    _is_image_only_message,
    _is_imessage_reaction,
    _preprocess_for_llm,
    _replace_urls,
    _url_to_token,
)


class TestUrlToToken:
    def test_firebase_image(self) -> None:
        url = "https://firebasestorage.googleapis.com/v0/b/bucket/o/photo.jpg"
        assert _url_to_token(url) == "[image]"

    def test_storage_googleapis_image(self) -> None:
        url = "https://storage.googleapis.com/bucket/photo.png"
        assert _url_to_token(url) == "[image]"

    def test_vcf_contact_card(self) -> None:
        url = "https://firebasestorage.googleapis.com/v0/b/bucket/o/contact.vcf"
        assert _url_to_token(url) == "[contact card]"

    def test_acme_link(self) -> None:
        assert _url_to_token("https://ditt.ai/some/path") == "[link]"

    def test_acme_ai_link(self) -> None:
        assert _url_to_token("https://acme.ai/profile") == "[link]"

    def test_youtube(self) -> None:
        assert _url_to_token("https://youtube.com/watch?v=abc") == "[youtube link]"

    def test_youtu_be(self) -> None:
        assert _url_to_token("https://youtu.be/abc123") == "[youtube link]"

    def test_instagram(self) -> None:
        assert _url_to_token("https://instagram.com/p/abc") == "[instagram link]"

    def test_tiktok(self) -> None:
        assert _url_to_token("https://tiktok.com/@user/video/123") == "[tiktok link]"

    def test_spotify(self) -> None:
        assert _url_to_token("https://spotify.com/track/abc") == "[spotify link]"

    def test_unknown_domain(self) -> None:
        assert _url_to_token("https://example.com/page") == "[link]"

    def test_www_prefix_stripped(self) -> None:
        assert _url_to_token("https://www.youtube.com/watch?v=xyz") == "[youtube link]"


class TestIsImageOnlyMessage:
    def test_firebase_url_is_image(self) -> None:
        msg = {"message": "https://firebasestorage.googleapis.com/v0/photo.jpg"}
        assert _is_image_only_message(msg) is True

    def test_media_wrapper_image(self) -> None:
        msg = {"message": "[media: https://storage.googleapis.com/bucket/img.png]"}
        assert _is_image_only_message(msg) is True

    def test_media_wrapper_contact_card(self) -> None:
        msg = {"message": "[media: https://firebasestorage.googleapis.com/v0/c.vcf]"}
        assert _is_image_only_message(msg) is True

    def test_plain_text_not_image(self) -> None:
        assert _is_image_only_message({"message": "Hello there"}) is False

    def test_youtube_link_not_image(self) -> None:
        assert _is_image_only_message({"message": "https://youtube.com/watch?v=abc"}) is False

    def test_empty_message_not_image(self) -> None:
        assert _is_image_only_message({"message": ""}) is False

    def test_missing_message_key(self) -> None:
        assert _is_image_only_message({}) is False

    def test_none_message_not_image(self) -> None:
        assert _is_image_only_message({"message": None}) is False


class TestReplaceUrls:
    def test_bare_firebase_url(self) -> None:
        text = "Check https://firebasestorage.googleapis.com/v0/photo.jpg out"
        assert _replace_urls(text) == "Check [image] out"

    def test_media_wrapper(self) -> None:
        text = "[media: https://storage.googleapis.com/bucket/img.png]"
        assert _replace_urls(text) == "[image]"

    def test_youtube_url(self) -> None:
        text = "Watch https://youtube.com/watch?v=abc"
        assert _replace_urls(text) == "Watch [youtube link]"

    def test_no_urls_unchanged(self) -> None:
        text = "Just a plain message"
        assert _replace_urls(text) == "Just a plain message"

    def test_multiple_urls(self) -> None:
        text = "https://youtube.com/watch?v=abc and https://instagram.com/p/xyz"
        result = _replace_urls(text)
        assert result == "[youtube link] and [instagram link]"


class TestCleanUserUpload:
    def test_single_image_with_text(self) -> None:
        text = (
            "NOTE: User uploaded an image. "
            "User Message: Hello there "
            "Image URL: https://firebasestorage.googleapis.com/img.jpg"
        )
        result = _clean_user_upload(text)
        assert result == 'User uploaded an image: "Hello there" [image]'

    def test_single_image_no_text(self) -> None:
        text = (
            "NOTE: User uploaded an image. "
            "User Message:  "
            "Image URL: https://firebasestorage.googleapis.com/img.jpg"
        )
        result = _clean_user_upload(text)
        assert result == "User uploaded an image [image]"

    def test_multiple_images(self) -> None:
        text = (
            "NOTE: User uploaded 3 images. "
            "User Message: Look at these "
            "Image URLs: https://firebasestorage.googleapis.com/img.jpg"
        )
        result = _clean_user_upload(text)
        assert result == 'User uploaded 3 image(s): "Look at these" [image]'

    def test_non_upload_text_passes_through(self) -> None:
        text = "Just a normal message https://youtube.com/watch?v=abc"
        result = _clean_user_upload(text)
        assert result == "Just a normal message [youtube link]"


class TestIsImessageReaction:
    @pytest.mark.parametrize("prefix", [
        "Loved ", "Liked ", "Disliked ", "Laughed at ", "Emphasized ", "Questioned ",
    ])
    def test_reaction_prefix_detected(self, prefix: str) -> None:
        msg = {"message": f'{prefix}"some text"'}
        assert _is_imessage_reaction(msg) is True

    def test_plain_message_not_reaction(self) -> None:
        assert _is_imessage_reaction({"message": "I love this!"}) is False

    def test_empty_message_not_reaction(self) -> None:
        assert _is_imessage_reaction({"message": ""}) is False

    def test_missing_message_not_reaction(self) -> None:
        assert _is_imessage_reaction({}) is False

    def test_case_sensitive(self) -> None:
        assert _is_imessage_reaction({"message": "loved something"}) is False


class TestPreprocessForLlm:
    def _make_msg(self, msg_type: str, text: str) -> dict:
        return {"type": msg_type, "message": text}

    def test_originals_not_mutated(self) -> None:
        original_text = "https://youtube.com/watch?v=abc"
        messages = [self._make_msg("user", original_text)]
        chat_ids = ["cid1"]
        _preprocess_for_llm(messages, chat_ids)
        assert messages[0]["message"] == original_text

    def test_url_replacement_pass3(self) -> None:
        messages = [self._make_msg("user", "Watch https://youtube.com/watch?v=abc")]
        llm_msgs, llm_cids, idx_map, _absorbed = _preprocess_for_llm(messages, ["cid1"])
        assert llm_msgs[0]["message"] == "Watch [youtube link]"
        assert idx_map == [0]

    def test_bot_image_absorbed_into_preceding(self) -> None:
        messages = [
            self._make_msg("user", "Hey"),
            self._make_msg("assistant", "https://firebasestorage.googleapis.com/v0/img.jpg"),
        ]
        chat_ids = ["c1", "c2"]
        llm_msgs, llm_cids, idx_map, _absorbed = _preprocess_for_llm(messages, chat_ids)
        assert len(llm_msgs) == 1
        assert llm_msgs[0]["message"] == "Hey [image]"
        assert idx_map == [0]

    def test_bot_image_only_no_preceding(self) -> None:
        messages = [
            self._make_msg("assistant", "https://firebasestorage.googleapis.com/v0/img.jpg"),
        ]
        llm_msgs, _, idx_map, _absorbed = _preprocess_for_llm(messages, ["c1"])
        assert len(llm_msgs) == 1
        assert llm_msgs[0]["message"] == "[image]"
        assert idx_map == [0]

    def test_user_image_upload_cleaned(self) -> None:
        text = (
            "NOTE: User uploaded an image. "
            "User Message: Hi "
            "Image URL: https://firebasestorage.googleapis.com/img.jpg"
        )
        messages = [self._make_msg("user", text)]
        llm_msgs, _, idx_map, _absorbed = _preprocess_for_llm(messages, ["c1"])
        assert llm_msgs[0]["message"] == 'User uploaded an image: "Hi" [image]'
        assert idx_map == [0]

    def test_index_map_reflects_absorbed(self) -> None:
        messages = [
            self._make_msg("user", "Hello"),
            self._make_msg("assistant", "https://firebasestorage.googleapis.com/img.jpg"),
            self._make_msg("user", "Okay"),
        ]
        chat_ids = ["c1", "c2", "c3"]
        llm_msgs, llm_cids, idx_map, _absorbed = _preprocess_for_llm(messages, chat_ids)
        assert len(llm_msgs) == 2
        assert idx_map == [0, 2]
        assert llm_cids == ["c1", "c3"]

    def test_empty_messages(self) -> None:
        llm_msgs, llm_cids, idx_map, _absorbed = _preprocess_for_llm([], [])
        assert llm_msgs == []
        assert llm_cids == []
        assert idx_map == []
