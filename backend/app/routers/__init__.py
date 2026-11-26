"""路由汇总：质量一致性扩展路由先注册，通用资源路由兜底按模块分派。"""
from __future__ import annotations

from app.routers import quality, resource

ROUTERS = [quality, resource]
