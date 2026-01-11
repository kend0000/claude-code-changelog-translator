import os
import hashlib
import requests
import time
from datetime import datetime, timezone, timedelta
from anthropic import Anthropic
from typing import Optional, Tuple, Dict

def get_jst_now():
    """日本時間（JST）で現在時刻を取得"""
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst)

class ChangelogTranslator:
    def __init__(self):
        self.api_key = os.environ.get('ANTHROPIC_API_KEY')
        self.discord_webhook = os.environ.get('DISCORD_WEBHOOK_URL')
        self.anthropic = Anthropic(api_key=self.api_key)
        
        # URL設定
        self.changelog_url = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
        
        # ファイルパス
        self.last_update_file = "last_update.txt"
        self.previous_content_file = "previous_content.md"
        self.output_file = "translated/changelog_ja.md"
        self.note_ready_file = "translated/note_ready.md"
        self.translation_count_file = "translation_count.txt"
        
        # 設定
        self.full_translation_interval = 10
        self.max_versions_to_translate = 50  # 最新50バージョンのみ翻訳
        
        # 翻訳エージェントのシステムプロンプト
        self.translation_system_prompt = """あなたはプロフェッショナルな英日翻訳者です。以下の原則に従って翻訳を行ってください。

## 基本方針
- 日本語ネイティブが読んで全く違和感のない、自然な日本語に翻訳する
- 直訳ではなく、意訳を基本とする
- 原文の意図・ニュアンス・トーンを正確に再現する

## 翻訳ルール

### 文体
- 技術文書・ビジネス文書：「です・ます調」
- カジュアルな文章：原文のトーンに合わせる
- 主語の省略：日本語として自然な場合は積極的に省略する

### 表現の最適化
- 英語特有の冗長な表現は簡潔な日本語に置き換える
- 受動態は能動態に変換することを検討する
- 関係代名詞の多用は、文を分割して読みやすくする
- 「〜することができる」→「〜できる」のように簡潔にする

### 避けるべき表現
- 「〜についての」の多用
- 「それは〜である」という直訳的な書き出し
- 不自然なカタカナ語の乱用
- 「私たちは」「あなたは」の過度な使用

### 専門用語
- IT・技術用語：一般的に使われるカタカナ表記を採用
- 固有名詞：原則として原語のまま
- 判断に迷う場合は「原語（日本語訳）」の形式で併記

## 出力形式
- 翻訳文のみを出力する
- 説明や注釈が必要な場合は、翻訳文の後に「---」で区切って記載
- ユーザーから指示がない限り、原文は繰り返さない

## 品質チェック
翻訳後、以下を自己確認してから出力する：
1. 日本語として自然に読めるか
2. 原文の情報が欠落していないか
3. 誤訳や意味の取り違えがないか"""
        
    def fetch_changelog(self) -> str:
        """GitHubからチェンジログを取得"""
        print(f"📥 {self.changelog_url} から取得中...")
        response = requests.get(self.changelog_url)
        response.raise_for_status()
        return response.text
    
    def extract_recent_versions(self, content: str, max_versions: int = None) -> str:
        """チェンジログから最新N個のバージョンのみを抽出"""
        if max_versions is None:
            max_versions = self.max_versions_to_translate
        
        lines = content.splitlines()
        output_lines = []
        versions_found = 0
        
        for line in lines:
            output_lines.append(line)
            
            # バージョン番号を検出（## で始まる行）
            if line.strip().startswith('## ') and not line.strip().startswith('## Changelog'):
                versions_found += 1
                
                if versions_found >= max_versions:
                    output_lines.append("\n---")
                    output_lines.append(f"\n*最新{max_versions}バージョンのみ表示*")
                    break
        
        result = "\n".join(output_lines)
        print(f"📌 最新{versions_found}バージョンを抽出（{len(result)} 文字）")
        return result
    
    def get_last_hash(self) -> Optional[str]:
        """前回のハッシュ値を取得"""
        try:
            with open(self.last_update_file, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            return None
    
    def save_hash(self, hash_value: str):
        """ハッシュ値を保存"""
        with open(self.last_update_file, 'w') as f:
            f.write(hash_value)
    
    def calculate_hash(self, content: str) -> str:
        """コンテンツのハッシュ値を計算"""
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_previous_content(self) -> Optional[str]:
        """前回の原文を取得"""
        try:
            with open(self.previous_content_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return None
    
    def save_previous_content(self, content: str):
        """前回の原文を保存"""
        with open(self.previous_content_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def extract_new_entries(self, old_content: str, new_content: str) -> Optional[str]:
        """チェンジログから新規追加部分のみを抽出"""
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        
        diff_count = len(new_lines) - len(old_lines)
        
        if diff_count <= 0:
            return None
        
        print(f"🔍 {diff_count}行の新規追加を検出")
        
        header_lines = 0
        for i, line in enumerate(new_lines[:10]):
            if line.strip().startswith('# '):
                header_lines = i + 1
                break
        
        start_index = header_lines
        end_index = min(diff_count + header_lines + 50, len(new_lines))
        
        new_entries = new_lines[start_index:end_index]
        
        return "\n".join(new_entries)
    
    def should_do_full_translation(self) -> bool:
        """全文翻訳が必要かチェック"""
        try:
            with open(self.translation_count_file, 'r') as f:
                count = int(f.read().strip())
        except:
            count = 0
        
        count += 1
        
        with open(self.translation_count_file, 'w') as f:
            f.write(str(count))
        
        if count >= self.full_translation_interval:
            with open(self.translation_count_file, 'w') as f:
                f.write('0')
            return True
        
        return False
    
    def translate_changelog(self, content: str, is_incremental: bool = False, max_retries: int = 3) -> Tuple[str, Dict]:
        """Claudeで翻訳（リトライ機能付き）"""
        
        for attempt in range(max_retries):
            try:
                return self._translate_with_stream(content, is_incremental)
            except Exception as e:
                error_msg = str(e)
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 10
                    print(f"\n⚠️  エラー発生（試行 {attempt + 1}/{max_retries}）")
                    print(f"   {error_msg[:150]}")
                    print(f"⏳ {wait_time}秒後に再試行します...\n")
                    time.sleep(wait_time)
                else:
                    print(f"\n❌ {max_retries}回の試行後も失敗しました")
                    raise
    
    def _translate_with_stream(self, content: str, is_incremental: bool = False) -> Tuple[str, Dict]:
        """ストリーミングAPIで翻訳（内部メソッド）"""
        if is_incremental:
            user_message = f"""以下はClaude Codeチェンジログの最新更新部分です。
これを既存の翻訳に追加できる形で日本語に翻訳してください。

補足指示：
- Markdown形式を維持してください
- バージョン番号、日付、コマンド例などはそのまま保持してください
- 固有名詞（Claude Code、MCP、Anthropic、GitHub、Windows、macOS など）は原語のまま使用してください
- 技術用語は一般的なカタカナ表記を使用してください

---

{content}"""
        else:
            user_message = f"""以下のClaude Codeのチェンジログ（Markdown形式）を日本語に翻訳してください。

補足指示：
- Markdown形式を維持してください
- バージョン番号、日付、コマンド例などはそのまま保持してください
- 固有名詞（Claude Code、MCP、Anthropic、GitHub、Windows、macOS など）は原語のまま使用してください
- 技術用語は一般的なカタカナ表記を使用してください

---

{content}"""
        
        print("🤖 Claude APIで翻訳中（ストリーミング）...")
        print(f"   モデル: claude-sonnet-4-5-20250929 (Sonnet 4.5)")
        print(f"   モード: {'差分翻訳' if is_incremental else '全文翻訳'}")
        
        translated_text = ""
        
        with self.anthropic.messages.stream(
            model="claude-sonnet-4-5-20250929",
            max_tokens=64000,
            temperature=0.3,
            system=self.translation_system_prompt,
            messages=[{
                "role": "user",
                "content": user_message
            }],
            timeout=600.0  # 10分のタイムアウト
        ) as stream:
            for text in stream.text_stream:
                translated_text += text
                if len(translated_text) % 1000 < 10:
                    print(".", end="", flush=True)
        
        print()
        
        # 使用量情報を取得
        final_message = stream.get_final_message()
        usage = {
            'input_tokens': final_message.usage.input_tokens,
            'output_tokens': final_message.usage.output_tokens
        }
        
        # コスト計算
        input_cost = (usage['input_tokens'] / 1_000_000) * 3
        output_cost = (usage['output_tokens'] / 1_000_000) * 15
        total_cost = input_cost + output_cost
        
        print()
        print(f"📊 トークン使用量:")
        print(f"   入力: {usage['input_tokens']:,} トークン")
        print(f"   出力: {usage['output_tokens']:,} トークン")
        print(f"   合計: {usage['input_tokens'] + usage['output_tokens']:,} トークン")
        print()
        print(f"💰 コスト詳細:")
        print(f"   入力: ${input_cost:.4f}")
        print(f"   出力: ${output_cost:.4f}")
        print(f"   合計: ${total_cost:.4f}（約{int(total_cost * 145)}円）")
        
        usage['total_cost'] = total_cost
        
        return translated_text, usage
    
    def save_translation(self, content: str):
        """翻訳結果を保存"""
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        
        header = f"""# Claude Code チェンジログ（日本語訳）

> 最終更新: {get_jst_now().strftime('%Y年%m月%d日 %H:%M')}（日本時間）  
> 原文: {self.changelog_url}  
> 表示: 最新{self.max_versions_to_translate}バージョン

---

"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write(header + content)
        
        with open(self.note_ready_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def append_translation(self, new_content: str):
        """既存の翻訳に新規部分を追加"""
        try:
            with open(self.output_file, 'r', encoding='utf-8') as f:
                existing = f.read()
            
            header_end = existing.find('---\n\n') + 5
            old_translation = existing[header_end:]
            
            updated_translation = new_content + "\n\n" + old_translation
            
            updated_header = f"""# Claude Code チェンジログ（日本語訳）

> 最終更新: {get_jst_now().strftime('%Y年%m月%d日 %H:%M')}（日本時間）  
> 原文: {self.changelog_url}  
> 表示: 最新{self.max_versions_to_translate}バージョン

---

"""
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write(updated_header + updated_translation)
            
            with open(self.note_ready_file, 'w', encoding='utf-8') as f:
                f.write(updated_translation)
                
        except FileNotFoundError:
            self.save_translation(new_content)
    
    def send_notification(self, message: str, usage: Dict = None):
        """Discord/Slackに通知を送信"""
        if not self.discord_webhook:
            print("⚠️  通知URLが設定されていません")
            return
        
        fields = [
            {
                "name": "保存場所",
                "value": f"`{self.output_file}`\n`{self.note_ready_file}` (note.com用)",
                "inline": False
            }
        ]
        
        if usage:
            fields.extend([
                {
                    "name": "トークン使用量",
                    "value": f"入力: {usage.get('input_tokens', 0):,}\n出力: {usage.get('output_tokens', 0):,}",
                    "inline": True
                },
                {
                    "name": "コスト",
                    "value": f"${usage.get('total_cost', 0):.4f}（約{int(usage.get('total_cost', 0) * 145)}円）",
                    "inline": True
                }
            ])
        
        fields.append({
            "name": "更新日時",
            "value": get_jst_now().strftime('%Y年%m月%d日 %H:%M') + "（日本時間）",
            "inline": False
        })
        
        payload = {
            "content": message,
            "username": "Claude Code Changelog Bot",
            "embeds": [{
                "title": "📝 Claude Code チェンジログ更新",
                "description": "翻訳が完了しました",
                "color": 5814783,
                "fields": fields
            }]
        }
        
        try:
            response = requests.post(self.discord_webhook, json=payload)
            response.raise_for_status()
            print("✅ 通知を送信しました")
        except Exception as e:
            print(f"❌ 通知の送信に失敗: {e}")
    
    def run(self):
        """メイン処理"""
        print("=" * 70)
        print("Claude Code Changelog Translator (最適化版)")
        print("=" * 70)
        print(f"実行時刻: {get_jst_now().strftime('%Y年%m月%d日 %H:%M:%S')}（日本時間）")
        print()
        
        try:
            current_content = self.fetch_changelog()
            current_hash = self.calculate_hash(current_content)
            
            file_size_kb = len(current_content.encode('utf-8')) / 1024
            print(f"📄 ファイルサイズ: {file_size_kb:.1f}KB")
            
            # 最新50バージョンのみを抽出
            limited_content = self.extract_recent_versions(current_content)
            limited_size_kb = len(limited_content.encode('utf-8')) / 1024
            print(f"   翻訳対象: {limited_size_kb:.1f}KB（最新{self.max_versions_to_translate}バージョン）")
            print()
            
            last_hash = self.get_last_hash()
            
            if current_hash == last_hash:
                print("✅ 変更なし - コスト: $0")
                print("=" * 70)
                return
            
            print("🔍 変更を検知しました！")
            print()
            
            old_content = self.get_previous_content()
            usage = None
            
            if old_content and not self.should_do_full_translation():
                print("📝 差分翻訳モード（コスト節約）")
                new_entries = self.extract_new_entries(old_content, current_content)
                
                if new_entries:
                    translated_new, usage = self.translate_changelog(new_entries, is_incremental=True)
                    self.append_translation(translated_new)
                else:
                    print("⚠️  差分抽出失敗 - 全文翻訳にフォールバック")
                    translated, usage = self.translate_changelog(limited_content)
                    self.save_translation(translated)
            else:
                reason = "初回" if not old_content else "定期メンテナンス"
                print(f"📝 全文翻訳モード（{reason}）")
                translated, usage = self.translate_changelog(limited_content)
                self.save_translation(translated)
            
            self.save_previous_content(current_content)
            self.save_hash(current_hash)
            
            print()
            print(f"💾 保存完了:")
            print(f"   - {self.output_file}")
            print(f"   - {self.note_ready_file} (note.com用)")
            print()
            
            print("📢 通知を送信中...")
            self.send_notification("翻訳完了！", usage)
            
            print("=" * 70)
            print("✅ 処理が正常に完了しました")
            print("=" * 70)
            
        except Exception as e:
            error_message = f"エラー: {str(e)}"
            print(f"❌ {error_message}")
            self.send_notification(f"⚠️ エラーが発生しました\n{error_message}")
            raise

if __name__ == "__main__":
    translator = ChangelogTranslator()
    translator.run()
