#!/usr/bin/env python3
"""Launch AutoPrestige API: python run.py"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RENDER", "") != "true",
    )
