import pytest

from embedding.config import Settings
from embedding.constants import DEFAULT_NGL
from embedding.errors import ConfigError


def test_image_limits_and_mmproj_default() -> None:
    settings = Settings.from_env({})
    assert settings.max_images == 4
    assert settings.max_image_bytes == 10485760
    assert settings.mmproj == "mmproj-embeddinggemma-2-Q8_0.gguf"


@pytest.mark.parametrize(
    "raw",
    [
        "mmproj-embeddinggemma-2-F16.gguf",
        "mmproj-embeddinggemma-2-audio-Q8_0.gguf",
        "audio-mmproj.gguf",
        "../mmproj-embeddinggemma-2-Q8_0.gguf",
        "mmproj-embeddinggemma-2-Q8_0.bin",
    ],
)
def test_mmproj_rejects_float16_audio_and_paths(raw: str) -> None:
    with pytest.raises(ConfigError) as captured:
        Settings.from_env({"EMBEDDING_MMPROJ": raw})
    assert captured.value.name == "EMBEDDING_MMPROJ"
    assert raw not in str(captured.value)


def test_ngl_defaults_to_all_layers() -> None:
    settings = Settings.from_env({})
    assert DEFAULT_NGL == 999
    assert settings.ngl == 999


def test_ngl_zero_keeps_every_layer_on_the_cpu() -> None:
    assert Settings.from_env({"EMBEDDING_LLAMA_NGL": "0"}).ngl == 0


def test_ngl_minus_one_means_all_layers() -> None:
    assert Settings.from_env({"EMBEDDING_LLAMA_NGL": "-1"}).ngl == -1


def test_ngl_accepts_the_upper_bound() -> None:
    assert Settings.from_env({"EMBEDDING_LLAMA_NGL": "999"}).ngl == 999


@pytest.mark.parametrize(
    "raw", ["nope", "", "  ", "-2", "1000", "1.5", "+", "99999999999999999999"]
)
def test_ngl_rejects_values_outside_the_contract(raw: str) -> None:
    with pytest.raises(ConfigError) as captured:
        Settings.from_env({"EMBEDDING_LLAMA_NGL": raw})
    assert captured.value.name == "EMBEDDING_LLAMA_NGL"
    if raw.strip():
        assert raw.strip() not in str(captured.value)
