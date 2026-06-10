"""プロキシモードの基底クラス。

新しいプロキシモードを追加する場合はこのクラスを継承する。
現在の実装:
  - StdioProxy: ローカル MCP サーバー（stdio）向け
予定:
  - HTTPProxy: 外部 MCP サーバー（Atlassian 等）向け
"""

from abc import ABC, abstractmethod
import argparse


class BaseProxy(ABC):
    def __init__(self, args: argparse.Namespace, pipeline) -> None:
        self.args = args
        self.pipeline = pipeline

    @abstractmethod
    def run(self) -> None:
        """プロキシを起動する。"""
