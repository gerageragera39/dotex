from __future__ import annotations

from typing import Any


def torch_status() -> dict[str, Any]:
    try:
        import torch  # type: ignore[import-not-found]

        cuda_available = bool(torch.cuda.is_available())
        data: dict[str, Any] = {
            "import_ok": True,
            "version": getattr(torch, "__version__", None),
            "cuda_available": cuda_available,
            "torch_cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
            "device_count": torch.cuda.device_count() if cuda_available else 0,
            "devices": [],
        }
        if cuda_available:
            for idx in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(idx)
                data["devices"].append(
                    {
                        "index": idx,
                        "name": torch.cuda.get_device_name(idx),
                        "total_memory_gb": round(props.total_memory / (1024**3), 2),
                    }
                )
        return data
    except Exception as exc:
        return {"import_ok": False, "cuda_available": False, "error": str(exc)}


def onnxruntime_status() -> dict[str, Any]:
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]

        providers = list(ort.get_available_providers())
        return {
            "import_ok": True,
            "version": getattr(ort, "__version__", None),
            "providers": providers,
            "cuda_provider_available": "CUDAExecutionProvider" in providers,
        }
    except Exception as exc:
        return {"import_ok": False, "providers": [], "cuda_provider_available": False, "error": str(exc)}


def gpu_diagnostics() -> dict[str, Any]:
    torch = torch_status()
    ort = onnxruntime_status()
    notes: list[str] = []
    if torch.get("cuda_available") and not ort.get("cuda_provider_available"):
        notes.append("PyTorch CUDA is available, but ONNX Runtime CUDAExecutionProvider is not. TexTeller/ONNX parts may run on CPU.")
    if not torch.get("cuda_available"):
        notes.append("PyTorch CUDA is not available in this Python environment; PyTorch-based OCR will run on CPU.")
    return {"torch": torch, "onnxruntime": ort, "notes": notes}
