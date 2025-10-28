#!/usr/bin/env python3
"""
Telegram Video Sorter Bot - PROFESSIONAL EDITION
Sorts video files by episode number and quality with dump channel support
Includes spoiler/blur image functionality and advanced features
Deployed on Render with webhook support
"""
import os
import re
import logging
import asyncio
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
from aiohttp import web

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration from environment
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

class VideoFile:
    def __init__(self, file_id: str, filename: str, caption: Optional[str] = None, file_type: str = 'document', message_id: int = None):
        self.file_id = file_id
        self.filename = filename
        self.full_caption = caption or ''  # Store complete caption
        self.caption = self._truncate_caption(caption) if caption else ''
        self.file_type = file_type
        self.message_id = message_id
        self.episode_number = self.extract_episode_number()
        self.season_number = self.extract_season_number()
        self.video_quality = self.extract_video_quality()
        self.parsed_info = self.parse_all()

    def _truncate_caption(self, caption: str, max_length: int = 1024) -> str:
        """Truncate caption if too long (Telegram limit is 1024 chars)"""
        if len(caption) <= max_length:
            return caption
        return caption[:max_length-3] + "..."

    def extract_season_episode(self) -> Optional[Tuple[int, int]]:
        """
        Extract season and episode numbers from filename.
        Enhanced to support multiple formats:
        - [S01-E07], [S1-E7], [S01E07]
        - S01E07, S1E7, s01e07
        - Season 1 Episode 7, Season 01 Episode 07
        - 1x07, 01x07
        - Episode 7, Ep 7, E07
        Returns: (season, episode) tuple or None
        """
        text = self.filename + " " + self.full_caption  # Search in both filename and caption
        
        patterns = [
            # Season and Episode patterns
            r'\[S(\d+)[-\s]*E(\d+)\]',           # [S01-E07], [S01 E07]
            r'S(\d+)E(\d+)',                      # S01E07
            r's(\d+)e(\d+)',                      # s01e07
            r'Season\s*(\d+)\s*Episode\s*(\d+)', # Season 1 Episode 7
            r'(\d+)x(\d+)',                       # 1x07
            r'\[(\d+)x(\d+)\]',                   # [1x07]
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                season = int(match.group(1))
                episode = int(match.group(2))
                return (season, episode)
        
        # Try to find episode-only patterns (assume season 1)
        episode_only_patterns = [
            r'Episode\s*(\d+)',                   # Episode 7
            r'Ep\.?\s*(\d+)',                     # Ep 7, Ep. 7
            r'\bE(\d+)\b',                        # E07
            r'EP(\d+)',                           # EP07
        ]
        
        for pattern in episode_only_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                episode = int(match.group(1))
                return (1, episode)  # Default to season 1
        
        return None
    
    def extract_episode_number(self) -> Optional[int]:
        """Extract episode number from filename or caption"""
        result = self.extract_season_episode()
        return result[1] if result else None
    
    def extract_season_number(self) -> Optional[int]:
        """Extract season number from filename or caption"""
        result = self.extract_season_episode()
        return result[0] if result else None
    
    def extract_video_quality(self) -> Optional[int]:
        """
        Extract video quality from filename or caption.
        Enhanced to support multiple formats:
        - [1080p], [1080], (1080p)
        - 1080p, 1080P
        - Full HD, FHD (1080p)
        - HD (720p)
        - 4K, UHD (2160p)
        - 8K (4320p)
        Returns: quality as integer (e.g., 1080) or None
        """
        text = self.filename + " " + self.full_caption
        
        # Quality name mappings
        quality_names = {
            '8K': 4320,
            'UHD': 2160,
            '4K': 2160,
            'QHD': 1440,
            'FULLHD': 1080,
            'FHD': 1080,
            'HD': 720,
            'SD': 480,
        }
        
        # Check for named qualities
        for name, quality in quality_names.items():
            if re.search(r'\b' + name + r'\b', text, re.IGNORECASE):
                return quality
        
        # Standard quality values
        common_qualities = [144, 240, 360, 480, 720, 1080, 1440, 2160, 4320]
        
        patterns = [
            r'[\[\(](\d+)p?[\]\)]',              # [1080p], (1080), [1080]
            r'(\d+)p(?:\s|$|\.|\]|\))',          # 1080p
            r'_(\d+)p_',                          # _1080p_
            r'-(\d+)p-',                          # -1080p-
            r'\.(\d+)p\.',                        # .1080p.
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                quality = int(match)
                if quality in common_qualities:
                    return quality
        
        return None
    
    def extract_language(self) -> Optional[str]:
        """Extract language from filename or caption"""
        text = self.filename + " " + self.full_caption
        
        languages = ['Hindi', 'English', 'Tamil', 'Telugu', 'Malayalam', 'Kannada', 
                    'Bengali', 'Marathi', 'Gujarati', 'Punjabi', 'Korean', 'Japanese',
                    'Spanish', 'French', 'German', 'Chinese', 'Multi Audio', 'Dual Audio']
        
        for lang in languages:
            if re.search(r'\b' + lang + r'\b', text, re.IGNORECASE):
                return lang
        
        return None
    
    def extract_codec(self) -> Optional[str]:
        """Extract video codec from filename or caption"""
        text = self.filename + " " + self.full_caption
        
        codecs = ['x264', 'x265', 'H264', 'H265', 'HEVC', 'AVC', 'VP9', 'AV1']
        
        for codec in codecs:
            if re.search(r'\b' + codec + r'\b', text, re.IGNORECASE):
                return codec
        
        return None
    
    def parse_all(self) -> dict:
        """Parse all information from filename and caption"""
        return {
            'filename': self.filename,
            'season': self.season_number,
            'episode': self.episode_number,
            'quality': self.video_quality,
            'language': self.extract_language(),
            'codec': self.extract_codec(),
            'full_caption': self.full_caption
        }

    def get_display_info(self) -> str:
        """Get formatted display information"""
        info = []
        if self.season_number:
            info.append(f"S{self.season_number:02d}")
        if self.episode_number:
            info.append(f"E{self.episode_number:02d}")
        if self.video_quality:
            info.append(f"{self.video_quality}p")
        if self.parsed_info.get('language'):
            info.append(self.parsed_info['language'])
        if self.parsed_info.get('codec'):
            info.append(self.parsed_info['codec'])
        
        return " | ".join(info) if info else "Unknown format"

    def __str__(self):
        return f"{self.get_display_info()}: {self.filename}"

class VideoSorterBot:
    def __init__(self):
        self.user_sessions: Dict[int, List[VideoFile]] = {}
        self.dump_channels: Dict[int, str] = {}
        self.user_stats: Dict[int, dict] = {}  # Track user statistics

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with interactive buttons"""
        keyboard = [
            [InlineKeyboardButton("📖 How to Use", callback_data='help_usage')],
            [InlineKeyboardButton("🎭 Spoiler Feature", callback_data='help_spoiler')],
            [InlineKeyboardButton("📊 My Statistics", callback_data='show_stats')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_message = (
            "🎬 **Video Sorter Bot - Professional Edition** 🎬\n\n"
            "Welcome! I'm your advanced video file organizer with powerful features:\n\n"
            "**✨ Key Features:**\n"
            "🔹 Smart episode sorting by quality\n"
            "🔹 Support for multiple naming formats\n"
            "🔹 Dump channel integration\n"
            "**🚀 Quick Commands:**\n"
            "• `/sequence` - Start collecting files\n"
            "• `/endsequence` - Sort and send files\n"
            "• `/spoiler` - Blur/hide images\n"
        )
        await update.message.reply_text(
            welcome_message, 
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = (
            "📚 **Detailed Help Guide** 📚\n\n"
            "**🎬 Video Sorting:**\n"
            "1. Use `/sequence` to start a new sorting session\n"
            "2. Send your video files (as documents or videos)\n"
            "3. Use `/endsequence` to process and sort\n"
            "4. Files will be sorted by quality (480p, 720p, 1080p, etc.)\n"
            "5. Within each quality, sorted by episode number\n\n"
            "**📝 Supported File Formats:**\n"
            "• `[S01-E07] Show Name [1080p].mkv`\n"
            "• `Show.Name.S01E07.1080p.WEB-DL.mkv`\n"
            "• `Show Name - 1x07 - Episode Title [720p].mp4`\n"
            "• `Episode 7 [1080p] [Hindi].mkv`\n"
            "• `Show.Name.Ep07.FHD.x264.mkv`\n\n"
            "**🎭 Spoiler Feature:**\n"
            "Reply to any photo with `/spoiler` to send it as blurred/hidden content.\n"
            "Users can click to reveal the image.\n\n"
            "**📢 Dump Channel:**\n"
            "Set a channel where sorted files will also be sent:\n"
            "• `/dump @YourChannel` - Set public channel\n"
            "• `/dump -1001234567890` - Set private channel\n"
            "• Bot must be admin in the channel!\n\n"
            "**📊 Statistics:**\n"
            "• `/stats` - View your usage statistics\n"
            "• Track files processed, sessions, and more\n\n"
            "**🔧 Other Commands:**\n"
            "• `/cancel` - Cancel current sorting session\n"
            "• `/preview` - Preview files before sorting\n"
            "• `/clear` - Clear dump channel setting\n\n"
            "**💡 Tips:**\n"
            "• Include episode and quality info in filename or caption\n"
            "• The bot reads FULL captions (no length limit internally)\n"
            "• Supports multiple quality naming: 1080p, FHD, Full HD, etc.\n"
            "• Can detect: Season, Episode, Quality, Language, Codec\n\n"
            "Need more help? Contact: @YourSupportChannel"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def sequence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sequence command"""
        user_id = update.effective_user.id
        self.user_sessions[user_id] = []

        # Initialize user stats if not exists
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                'total_files': 0,
                'total_sessions': 0,
                'last_session': None
            }

        message = (
            "📁 **File Collection Started!** 📁\n\n"
            "✅ Ready to receive your files!\n\n"
            
            "1. Send me your video files (documents or videos)\n"

        )
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    async def preview_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Preview collected files before sorting"""
        user_id = update.effective_user.id

        if user_id not in self.user_sessions or not self.user_sessions[user_id]:
            await update.message.reply_text(
                "❌ No files in session. Use `/sequence` first!"
            )
            return

        files = self.user_sessions[user_id]
        preview = f"📋 **Preview: {len(files)} Files Collected**\n\n"

        valid_count = 0
        invalid_count = 0

        for idx, file in enumerate(files, 1):
            if file.episode_number and file.video_quality:
                preview += f"✅ {idx}. {file.get_display_info()}\n"
                valid_count += 1
            else:
                preview += f"⚠️ {idx}. {file.filename[:50]}... (Cannot parse)\n"
                invalid_count += 1

        preview += f"\n📊 **Summary:**\n"
        preview += f"✅ Valid files: {valid_count}\n"
        preview += f"⚠️ Files with issues: {invalid_count}\n\n"
        preview += f"Use `/endsequence` to process or `/cancel` to abort."

        await update.message.reply_text(preview, parse_mode=ParseMode.MARKDOWN)

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel current sorting session"""
        user_id = update.effective_user.id

        if user_id not in self.user_sessions:
            await update.message.reply_text("❌ No active session to cancel.")
            return

        file_count = len(self.user_sessions[user_id])
        del self.user_sessions[user_id]

        await update.message.reply_text(
            f"✅ **Session cancelled!**\n\n"
            f"Removed {file_count} files from queue.\n"
            f"Use `/sequence` to start a new session.",
            parse_mode=ParseMode.MARKDOWN
        )

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user statistics"""
        user_id = update.effective_user.id

        if user_id not in self.user_stats:
            await update.message.reply_text(
                "📊 **Your Statistics**\n\n"
                "No activity yet! Start using the bot with `/sequence`"
            )
            return

        stats = self.user_stats[user_id]
        stats_text = (
            f"📊 **Your Statistics**\n\n"
            f"📁 Total files processed: {stats['total_files']}\n"
            f"🔄 Total sessions: {stats['total_sessions']}\n"
        )

        if stats['last_session']:
            stats_text += f"🕐 Last session: {stats['last_session']}\n"

        current_session = len(self.user_sessions.get(user_id, []))
        if current_session > 0:
            stats_text += f"\n📥 Current session: {current_session} files\n"

        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)

    async def dump_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /dump command to set a dump channel"""
        user_id = update.effective_user.id
        
        if not context.args:
            current_dump = self.dump_channels.get(user_id, "Not set")
            await update.message.reply_text(
                f"📢 **Dump Channel Configuration**\n\n"
                f"Current dump channel: `{current_dump}`\n\n"
                f"**To set a dump channel:**\n"
                f"• `/dump @YourChannelUsername`\n"
                f"• `/dump -1001234567890` (private channel ID)\n\n"
                f"**To clear:**\n"
                f"• `/clear` - Remove dump channel\n\n"
                f"**Requirements:**\n"
                f"✅ Bot must be added to channel\n"
                f"✅ Bot must have admin rights\n"
                f"✅ Bot needs 'Post Messages' permission",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        channel = context.args[0]
        
        # Test if bot can send to the channel
        try:
            test_message = await context.bot.send_message(
                chat_id=channel,
                text="🔧 **Dump Channel Test**\n\nThis channel has been set as your dump channel!\n\n✅ Test successful!",
                parse_mode=ParseMode.MARKDOWN
            )
            await asyncio.sleep(3)
            await context.bot.delete_message(chat_id=channel, message_id=test_message.message_id)
            
            self.dump_channels[user_id] = channel
            await update.message.reply_text(
                f"✅ **Dump channel configured!**\n\n"
                f"Channel: `{channel}`\n\n"
                f"📤 All sorted files will be sent to:\n"
                f"1. Your chat (private)\n"
                f"2. Dump channel (backup)\n\n"
                f"Use `/clear` to remove dump channel.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error testing dump channel {channel}: {e}")
            await update.message.reply_text(
                f"❌ **Failed to set dump channel!**\n\n"
                f"Error: `{str(e)}`\n\n"
                f"**Troubleshooting:**\n"
                f"1. Make sure bot is added to the channel\n"
                f"2. Give bot admin permissions\n"
                f"3. Enable 'Post Messages' permission\n"
                f"4. Check channel ID/username is correct\n"
                f"5. For private channels, use numeric ID",
                parse_mode=ParseMode.MARKDOWN
            )

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear dump channel setting"""
        user_id = update.effective_user.id

        if user_id in self.dump_channels:
            channel = self.dump_channels[user_id]
            del self.dump_channels[user_id]
            await update.message.reply_text(
                f"✅ **Dump channel removed!**\n\n"
                f"Removed: `{channel}`\n\n"
                f"Files will now only be sent to your chat.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "❌ No dump channel configured.\n\n"
                "Use `/dump @Channel` to set one."
            )

    async def spoiler_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /spoiler command to send photos with spoiler/blur effect"""
        if not update.message.reply_to_message:
            keyboard = [
                [InlineKeyboardButton("📖 How to Use Spoiler", callback_data='help_spoiler')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "🎭 **Spoiler Feature**\n\n"
                "**How to use:**\n"
                "1. Someone sends a photo\n"
                "2. Reply to it with `/spoiler`\n"
                "3. Bot resends as blurred/hidden image\n"
                "4. Click to reveal!\n\n"
                "**Supported:**\n"
                "✅ Photos\n"
                "✅ Image documents (.jpg, .png, .gif)\n\n"
                "**Try it:** Reply to any photo with `/spoiler`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return
        
        replied_message = update.message.reply_to_message
        
        # Handle replied photo
        if replied_message.photo:
            try:
                # Get the highest quality photo
                photo = replied_message.photo[-1]
                
                # Send photo with spoiler
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=photo.file_id,
                    caption=replied_message.caption,
                    has_spoiler=True
                )
                await update.message.reply_text(
                    "✅ **Spoiler sent!**\n\n"
                    "👆 Click the blurred image to reveal it.\n"
                    "🎭 Perfect for hiding spoilers!",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Error sending spoiler photo: {e}")
                await update.message.reply_text(
                    f"❌ Failed to send spoiler: `{str(e)}`",
                    parse_mode=ParseMode.MARKDOWN
                )
        
        # Handle replied document (if it's an image)
        elif replied_message.document:
            mime_type = replied_message.document.mime_type or ""
            if mime_type.startswith('image/'):
                try:
                    # Send document as photo with spoiler
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=replied_message.document.file_id,
                        caption=replied_message.caption,
                        has_spoiler=True
                    )
                    await update.message.reply_text(
                        "✅ **Spoiler sent!**\n\n"
                        "👆 Click the blurred image to reveal it.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Error sending spoiler document: {e}")
                    await update.message.reply_text(
                        f"❌ Failed: `{str(e)}`",
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await update.message.reply_text(
                    f"❌ This is not an image file.\n\n"
                    f"File type: `{mime_type}`\n"
                    f"Please reply to a photo or image document.",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await update.message.reply_text(
                "❌ **Invalid target!**\n\n"
                "Please reply to:\n"
                "✅ A photo\n"
                "✅ An image document\n\n"
                "Current message type is not supported."
            )
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()

        if query.data == 'help_usage':
            await query.message.reply_text(
                "📖 **How to Use Video Sorter**\n\n"
                "**Step-by-step:**\n"
                "1️⃣ Use `/sequence` to start\n"
                "2️⃣ Send your video files\n"
                "3️⃣ Use `/endsequence` to sort\n"
                "4️⃣ Receive sorted files!\n\n"
                "**File naming tips:**\n"
                "• Include season/episode: S01E07\n"
                "• Include quality: 1080p, 720p\n"
                "• Can be in filename or caption\n\n"
                "Use `/help` for detailed guide!",
                parse_mode=ParseMode.MARKDOWN
            )
        elif query.data == 'help_spoiler':
            await query.message.reply_text(
                "🎭 **Spoiler Feature Guide**\n\n"
                "**What it does:**\n"
                "Converts regular photos into blurred/hidden images that users must click to reveal.\n\n"
                "**How to use:**\n"
                "1. Find a photo message\n"
                "2. Reply to it with `/spoiler`\n"
                "3. Bot sends blurred version\n"
                "4. Click to reveal!\n\n"
                "**Perfect for:**\n"
                "🎬 Movie/show spoilers\n"
                "🎮 Game screenshots\n"
                "📰 News reveals\n"
                "🎁 Surprise reveals",
                parse_mode=ParseMode.MARKDOWN
            )
        elif query.data == 'show_stats':
            user_id = query.from_user.id
            if user_id in self.user_stats:
                stats = self.user_stats[user_id]
                await query.message.reply_text(
                    f"📊 **Your Statistics**\n\n"
                    f"📁 Files processed: {stats['total_files']}\n"
                    f"🔄 Sessions completed: {stats['total_sessions']}\n"
                    f"🕐 Last session: {stats.get('last_session', 'N/A')}\n\n"
                    f"Use `/stats` anytime to check!",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.message.reply_text(
                    "📊 No statistics yet!\n\nStart using `/sequence` to begin tracking."
                )

    async def send_file_to_dump(self, context: ContextTypes.DEFAULT_TYPE, dump_chat_id: str, video_file: VideoFile):
        """Send a file to the dump channel with error handling"""
        try:
            if video_file.file_type == 'video':
                await context.bot.send_video(
                    chat_id=dump_chat_id,
                    video=video_file.file_id,
                    caption=video_file.full_caption  # Use full caption
                )
            else:
                await context.bot.send_document(
                    chat_id=dump_chat_id,
                    document=video_file.file_id,
                    caption=video_file.full_caption  # Use full caption
                )
            await asyncio.sleep(0.5)
            return True
        except Exception as e:
            logger.error(f"Error sending file to dump: {video_file.filename} - {e}")
            return False

    async def endsequence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /endsequence command with enhanced sorting"""
        user_id = update.effective_user.id

        if user_id not in self.user_sessions or not self.user_sessions[user_id]:
            await update.message.reply_text(
                "❌ No files in session!\n\nUse `/sequence` first and send files."
            )
            return

        files = self.user_sessions[user_id]
        file_count = len(files)

        processing_msg = await update.message.reply_text(
            f"⚙️ **Processing {file_count} files...**\n\n"
            f"🔍 Analyzing episodes and quality\n"
            f"📊 Grouping by quality tiers\n"
            f"🔢 Sorting by episode numbers",
            parse_mode=ParseMode.MARKDOWN
        )

        # Filter valid files
        valid_files = [f for f in files if f.episode_number is not None and f.video_quality is not None]
        invalid_files = [f for f in files if f.episode_number is None or f.video_quality is None]

        if not valid_files:
            await update.message.reply_text(
                "❌ **No valid files found!**\n\n"
                "Files couldn't be parsed. Make sure they include:\n"
                "• Episode number (E07, Episode 7, etc.)\n"
                "• Quality (1080p, 720p, FHD, etc.)\n\n"
                "Check `/help` for supported formats."
            )
            del self.user_sessions[user_id]
            return

        # Group files by quality
        quality_groups = {}
        for f in valid_files:
            if f.video_quality not in quality_groups:
                quality_groups[f.video_quality] = []
            quality_groups[f.video_quality].append(f)

        # Sort within each quality group by episode
        for quality in quality_groups:
            quality_groups[quality].sort(key=lambda x: (x.season_number or 1, x.episode_number))

        # Sort quality keys in ascending order
        sorted_qualities = sorted(quality_groups.keys())

        dump_chat_id = self.dump_channels.get(user_id)
        dump_failed_files = []

        await processing_msg.edit_text(
            f"✅ **Analysis Complete!**\n\n"
            f"📊 Valid files: {len(valid_files)}/{file_count}\n"
            f"🎯 Quality groups: {len(quality_groups)}\n"
            f"📤 Starting distribution...",
            parse_mode=ParseMode.MARKDOWN
        )

        # Send sorted files
        for quality in sorted_qualities:
            files_in_quality = quality_groups[quality]
            
            # Quality header
            quality_name = {
                4320: "8K/UHD", 2160: "4K/UHD", 1440: "QHD",
                1080: "Full HD", 720: "HD", 480: "SD", 360: "LD", 240: "LD"
            }.get(quality, f"{quality}p")
            
            episodes = sorted(set([f.episode_number for f in files_in_quality]))
            episode_range = f"E{min(episodes):02d}-E{max(episodes):02d}" if episodes else "Unknown"
            
            header_text = (
                f"📺 **{quality}p ({quality_name}) EPISODES** 📺\n\n"
                f"📊 Count: {len(files_in_quality)} files\n"
                f"📝 Range: {episode_range}\n"
                f"⬇️ Sending now..."
            )
            
            await update.message.reply_text(header_text, parse_mode=ParseMode.MARKDOWN)
            
            if dump_chat_id:
                try:
                    await context.bot.send_message(
                        chat_id=dump_chat_id,
                        text=header_text,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.error(f"Error sending header to dump: {e}")

            # Send each file
            for video_file in files_in_quality:
                # Send to user
                try:
                    if video_file.file_type == 'video':
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=video_file.file_id,
                            caption=video_file.full_caption  # Full caption
                        )
                    else:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=video_file.file_id,
                            caption=video_file.full_caption  # Full caption
                        )
                except Exception as e:
                    logger.error(f"Error sending to user: {e}")

                # Send to dump
                if dump_chat_id:
                    success = await self.send_file_to_dump(context, dump_chat_id, video_file)
                    if not success:
                        dump_failed_files.append(video_file.filename)

                await asyncio.sleep(0.3)  # Rate limit protection

        # Completion message to dump
        if dump_chat_id:
            try:
                completion = (
                    "✅ **SORTING COMPLETE** ✅\n\n"
                    f"📊 Total: {len(valid_files)} files\n"
                    f"🎯 Quality groups: {len(quality_groups)}\n\n"
                    f"**Distribution:**\n"
                )
                
                for quality in sorted_qualities:
                    count = len(quality_groups[quality])
                    episodes = sorted(set([f.episode_number for f in quality_groups[quality]]))
                    ep_range = f"E{min(episodes):02d}-E{max(episodes):02d}"
                    completion += f"• {quality}p: {count} files ({ep_range})\n"
                
                completion += "\n🎉 All files delivered!"
                
                await context.bot.send_message(
                    chat_id=dump_chat_id,
                    text=completion,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Error sending completion to dump: {e}")

        # Update statistics
        self.user_stats[user_id]['total_files'] += len(valid_files)
        self.user_stats[user_id]['total_sessions'] += 1
        self.user_stats[user_id]['last_session'] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Summary for user
        summary = await self.generate_summary(
            valid_files, file_count, quality_groups, 
            sorted_qualities, invalid_files, dump_failed_files
        )
        await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)

        # Clear session
        del self.user_sessions[user_id]

    async def generate_summary(self, valid_files: List[VideoFile], total_files: int, 
                              quality_groups: Dict, sorted_qualities: List, 
                              invalid_files: List[VideoFile], dump_failed_files: List[str]) -> str:
        """Generate comprehensive summary"""
        summary = "✅ **SORTING COMPLETE!** ✅\n\n"
        summary += f"📊 **Overall Statistics:**\n"
        summary += f"• Total files received: {total_files}\n"
        summary += f"• Successfully processed: {len(valid_files)}\n"
        summary += f"• Quality groups: {len(quality_groups)}\n\n"

        summary += f"🎯 **Quality Distribution:**\n"
        for quality in sorted_qualities:
            files = quality_groups[quality]
            episodes = sorted(set([f.episode_number for f in files]))
            ep_range = f"E{min(episodes):02d}-E{max(episodes):02d}" if episodes else "N/A"
            
            # Get additional info
            languages = set([f.parsed_info.get('language') for f in files if f.parsed_info.get('language')])
            lang_str = f" ({', '.join(languages)})" if languages else ""
            
            summary += f"• {quality}p: {len(files)} episodes ({ep_range}){lang_str}\n"

        if invalid_files:
            summary += f"\n⚠️ **Files with issues:** {len(invalid_files)}\n"
            summary += "These files couldn't be parsed. Check naming format.\n"

        if dump_failed_files:
            summary += f"\n❌ **Dump channel errors:** {len(dump_failed_files)} files\n"

        summary += "\n🎉 **Session complete!**\n"
        summary += "Files sent in quality order (lowest to highest)\n\n"
        summary += "Use `/sequence` to start a new session!"

        return summary

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle document file uploads with full caption support"""
        user_id = update.effective_user.id

        if user_id not in self.user_sessions:
            await update.message.reply_text(
                "❌ No active session!\n\nUse `/sequence` first to start collecting files."
            )
            return

        document = update.message.document
        if document:
            filename = document.file_name or "unknown_file"
            # Get FULL caption without truncation
            full_caption = update.message.caption or ''
            
            video_file = VideoFile(
                document.file_id, 
                filename, 
                full_caption, 
                'document',
                update.message.message_id
            )
            self.user_sessions[user_id].append(video_file)

            # Generate status message
            status_parts = []
            if video_file.season_number:
                status_parts.append(f"S{video_file.season_number:02d}")
            if video_file.episode_number:
                status_parts.append(f"E{video_file.episode_number:02d}")
            if video_file.video_quality:
                status_parts.append(f"{video_file.video_quality}p")
            
            parsed_info = video_file.parsed_info
            if parsed_info.get('language'):
                status_parts.append(parsed_info['language'])
            if parsed_info.get('codec'):
                status_parts.append(parsed_info['codec'])

            if status_parts:
                status = "✅ " + " | ".join(status_parts)
            else:
                status = "⚠️ Could not parse episode/quality info"

            session_count = len(self.user_sessions[user_id])
            
            await update.message.reply_text(
                f"📁 **File received!**\n\n"
                f"📝 {filename[:60]}{'...' if len(filename) > 60 else ''}\n"
                f"{status}\n\n",
                parse_mode=ParseMode.MARKDOWN
            )

    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle video file uploads with full caption support"""
        user_id = update.effective_user.id

        if user_id not in self.user_sessions:
            await update.message.reply_text(
                "❌ No active session!\n\nUse `/sequence` first to start collecting files."
            )
            return

        video = update.message.video
        if video:
            filename = video.file_name or f"video_{video.file_id[:8]}.mp4"
            # Get FULL caption
            full_caption = update.message.caption or ''

            video_file = VideoFile(
                video.file_id, 
                filename, 
                full_caption, 
                'video',
                update.message.message_id
            )
            self.user_sessions[user_id].append(video_file)

            # Generate detailed status
            status_parts = []
            if video_file.season_number:
                status_parts.append(f"S{video_file.season_number:02d}")
            if video_file.episode_number:
                status_parts.append(f"E{video_file.episode_number:02d}")
            if video_file.video_quality:
                status_parts.append(f"{video_file.video_quality}p")
            
            parsed_info = video_file.parsed_info
            if parsed_info.get('language'):
                status_parts.append(parsed_info['language'])
            if parsed_info.get('codec'):
                status_parts.append(parsed_info['codec'])

            if status_parts:
                status = "✅ " + " | ".join(status_parts)
            else:
                status = "⚠️ Could not parse episode/quality info"

            session_count = len(self.user_sessions[user_id])

            await update.message.reply_text(
                f"🎥 **Video received!**\n\n"
                f"📝 {filename[:60]}{'...' if len(filename) > 60 else ''}\n"
                f"{status}\n\n"
                f"📊 Session: {session_count} files\n"
                f"💾 Caption: {len(full_caption)} chars {'(full caption saved)' if len(full_caption) > 100 else ''}",
                parse_mode=ParseMode.MARKDOWN
            )

# ============================================
# RENDER WEBHOOK SETUP
# ============================================
async def health_check(request):
    """Health check for Render"""
    return web.json_response({
        'status': 'healthy',
        'service': 'Video Sorter Bot - Professional',
        'platform': 'Render',
        'version': '2.0',
        'features': [
            'Video Sorting',
            'Spoiler Images',
            'Dump Channel',
            'Full Caption Support',
            'Advanced Parsing',
            'User Statistics'
        ]
    })

async def webhook_handler(request, application):
    """Handle incoming webhook updates"""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500, text=str(e))

async def setup_webhook(application):
    """Setup webhook for Render"""
    if not WEBHOOK_URL:
        logger.error("❌ WEBHOOK_URL not set!")
        return False
    
    webhook_url = WEBHOOK_URL.strip().rstrip('/')
    
    if not webhook_url.startswith('http://') and not webhook_url.startswith('https://'):
        webhook_url = f"https://{webhook_url}"
    
    webhook_url = f"{webhook_url}/webhook"
    
    logger.info(f"🔧 Setting webhook to: {webhook_url}")
    
    try:
        result = await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES
        )
        if result:
            logger.info(f"✅ Webhook set successfully: {webhook_url}")
            return True
        else:
            logger.error(f"❌ Webhook setup returned False")
            return False
    except Exception as e:
        logger.error(f"❌ Webhook setup failed: {e}")
        return False

async def start_server(application):
    """Start aiohttp web server for Render"""
    app = web.Application()
    
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', health_check)
    app.router.add_get('/', health_check)
    app.router.add_post('/webhook', lambda req: webhook_handler(req, application))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    logger.info(f"🌐 Server started on 0.0.0.0:{PORT}")
    return runner

def main():
    """Main function to run the bot on Render"""
    
    if not BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set!")
        return

    logger.info("=" * 60)
    logger.info("🎬 Video Sorter Bot - Professional Edition")
    logger.info("🖥️ Platform: Render")
    logger.info(f"🌐 Port: {PORT}")
    logger.info(f"🔗 Webhook URL: {WEBHOOK_URL}")
    logger.info("=" * 60)

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Bot commands
    commands = [
        BotCommand("start", "Start the bot and get help"),
        BotCommand("help", "Detailed help guide"),
        BotCommand("sequence", "Start collecting video files"),
        BotCommand("endsequence", "Sort and send collected files"),
        BotCommand("preview", "Preview collected files"),
        BotCommand("cancel", "Cancel current session"),
        BotCommand("spoiler", "Send photo as spoiler/blur"),
        BotCommand("dump", "Set dump channel"),
        BotCommand("clear", "Clear dump channel"),
        BotCommand("stats", "View your statistics"),
    ]
    
    bot = VideoSorterBot()

    # Add handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("sequence", bot.sequence_command))
    application.add_handler(CommandHandler("endsequence", bot.endsequence_command))
    application.add_handler(CommandHandler("preview", bot.preview_command))
    application.add_handler(CommandHandler("cancel", bot.cancel_command))
    application.add_handler(CommandHandler("dump", bot.dump_command))
    application.add_handler(CommandHandler("clear", bot.clear_command))
    application.add_handler(CommandHandler("spoiler", bot.spoiler_command))
    application.add_handler(CommandHandler("stats", bot.stats_command))
    application.add_handler(CallbackQueryHandler(bot.button_callback))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    application.add_handler(MessageHandler(filters.VIDEO, bot.handle_video))

    async def post_init(app):
        """Post initialization - set commands"""
        await app.bot.set_my_commands(commands)
        logger.info("✅ Bot commands set")

    application.post_init = post_init

    # Run with webhook
    async def run_webhook():
        """Run bot with webhook"""
        try:
            await application.initialize()
            await application.start()
            
            if not await setup_webhook(application):
                logger.error("❌ Webhook setup failed")
                return
            
            runner = await start_server(application)
            
            logger.info("✅ Bot is ready and running!")
            logger.info("🎉 Professional Edition Active")
            logger.info("=" * 60)
            
            while True:
                await asyncio.sleep(3600)
                
        except KeyboardInterrupt:
            logger.info("👋 Shutting down...")
        finally:
            await application.stop()
            await application.shutdown()
            if 'runner' in locals():
                await runner.cleanup()

    # Check platform
    if os.getenv('RENDER'):
        logger.info("🌐 Running on Render with webhook")
        asyncio.run(run_webhook())
    else:
        logger.info("💻 Running locally with polling")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
