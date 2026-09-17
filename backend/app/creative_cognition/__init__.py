"""Creative Cognition — conceptual exploration above the deterministic engine.

Imports nothing concrete: the provider arrives through a protocol and is built in
composition.py, which is what keeps tests/test_architecture.py green.
"""
from app.creative_cognition.engine import CognitionConfig, CreativeCognition

__all__ = ["CreativeCognition", "CognitionConfig"]
