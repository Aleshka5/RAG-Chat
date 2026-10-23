import pytest

from embedding.config import Settings
from embedding.constants import DEFAULT_NGL
from embedding.errors import ConfigError


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


def test_mmproj_defaults_to_the_pinned_projector() -> None:
    assert Settings.from_env({}).mmproj == "mmproj-embeddinggemma-2-Q8_0.gguf"


@pytest.mark.parametrize(
    "raw",
    [
        "embeddinggemma-2-Q8_0.gguf",
        "mmproj-embeddinggemma-2-Q8_0.safetensors",
        "/models/mmproj-embeddinggemma-2-Q8_0.gguf",
        " mmproj-embeddinggemma-2-Q8_0.gguf",
        "",
    ],
)
def test_mmproj_must_name_a_projector_file(raw: str) -> None:
    with pytest.raises(ConfigError) as captured:
        Settings.from_env({"EMBEDDING_MMPROJ": raw})
    assert captured.value.name == "EMBEDDING_MMPROJ"


def test_image_limits_have_defaults_and_bounds() -> None:
    settings = Settings.from_env({})
    assert settings.max_images == 4
    assert settings.max_image_bytes == 10 * 1024 * 1024

    for raw in ("0", "-1", "65", "nope"):
        with pytest.raises(ConfigError) as captured:
            Settings.from_env({"EMBEDDING_MAX_IMAGES": raw})
        assert captured.value.name == "EMBEDDING_MAX_IMAGES"
