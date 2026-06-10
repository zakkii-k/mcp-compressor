"""パイプラインプロセッサの基底クラス。"""

from abc import ABC, abstractmethod


class BaseProcessor(ABC):
    @abstractmethod
    def should_apply(self, text: str) -> bool:
        """このプロセッサを適用すべきか判定する。"""

    @abstractmethod
    def process(self, text: str) -> tuple[str, bool]:
        """テキストを処理する。戻り値: (処理済みテキスト, 変更されたか)"""
