#!/usr/bin/env python3
"""
Telegram Video Sorter Bot
A bot that sorts video files by episode number and quality with dump and log channel support
"""
import os
import re
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "-1003057761446")  # Fallback to provided ID

class VideoFile:
    def __init__(self, file_id: str, filename: str, caption: Optional[str] = None, file_type: str = 'document'):
        self.file_id = file_id
        self.filename = filename
        self.caption = caption or ''
        self.file_type = file_type
        self.episode_number = self.extract_episode_number()
        self.video_quality = self.extract_video_quality()

    def extract_episode_number(self) -> Optional[int]:
        """Extract episode number from filename or caption (e.g., [S01-E07] -> 7)"""
        pattern = r'\[S\d+-E(\d+)\]'
        for text in [self.filename, self.caption]:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None

    def extract_video_quality(self) -> Optional[int]:
        """Extract video quality from filename or caption (e.g., [1080] or [1080P] -> 1080)"""
        pattern = r'\[S\d+-E\d+\].*\[(\d+)(P)?\]'  # Matches [1080] or [1080P]
        for text in [self.filename, self.caption]:
            match = re.search(pattern, text)
            if match:
                quality = int(match.group(1))
                common_qualities = [144, 240, 360, 480, 720, 1080, 1440, 2160]
                return quality if quality in common_qualities else None
        return None

    def __str__(self):
        return f"Episode {self.episode_number}, Quality {self.video_quality}: {self.filename}"

class VideoSorterBot:
    def __init__(self):
        self.user_sessions: Dict[int, List[VideoFile]] = {}
        self.dump_channels: Dict[int, str] = {}  # Store dump channel ID or username per user
        self.log_channel_id = LOG_CHANNEL_ID

    async def log_action(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, action: str, details: str = ""):
        """Log user actions to the designated log channel"""
        if self.log_channel_id:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
            log_message = (
                f"🕒 {timestamp}\n"
                f"👤 User: {username} (ID: {user_id})\n"
                f"📋 Action: {action}\n"
                f"📝 Details: {details}"
            )
            try:
                await context.bot.send_message(chat_id=self.log_channel_id, text=log_message)
            except Exception as e:
                logger.error(f"Failed to log action to channel {self.log_channel_id}: {e}")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        current_time = datetime.now().strftime("%I:%M %p IST")
        greeting = "Good evening" if datetime.now().hour >= 17 else "Hello"
        welcome_message = (
            f"{greeting}! 🎬 **Video Sorter Bot** 🎬\n\n"
            f"Current time: {current_time} on {datetime.now().strftime('%A, %B %d, %Y')}. "
            "Welcome! I help you organize and sequence video files (like TV show episodes) "
            "based on their episode number and quality.\n\n"
            "**How it works:**\n"
            "1. Use `/sequence` to start sending me your video files\n"
            "2. Send me your video files one by one\n"
            "3. Use `/endsequence` when you're done\n"
            "4. I'll sort them by quality (480p, 720p, 1080p) and episode number, "
            "sending each quality block separately!\n"
            "5. Use `/dump <channel>` to set a private or public dump channel for sorted files "
            "(add the bot to the channel first).\n\n"
            "**File format expected:** `[S01-E07] Show Name [1080P] [Single].mkv`\n\n"
            "Ready to get started? Use `/sequence` to begin!"
        )
        await update.message.reply_text(welcome_message, parse_mode='Markdown')
        username = update.effective_user.username or "Unknown"
        await self.log_action(context, update.effective_user.id, username, "Started the bot")

    async def sequence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sequence command"""
        user_id = update.effective_user.id
        self.user_sessions[user_id] = []
        message = (
            "📁 **Ready to receive files!** 📁\n\n"
            "Please start sending me your video files. I'll collect them and sort them "
            "when you use `/endsequence`.\n\n"
            "**Tip:** Make sure your files follow the naming convention:\n"
            "`[S01-E07] Show Name [1080P] [Single].extension`"
        )
        await update.message.reply_text(message, parse_mode='Markdown')
        username = update.effective_user.username or "Unknown"
        await self.log_action(context, user_id, username, "Started sequence collection")

    async def dump_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /dump command to set a dump channel"""
        user_id = update.effective_user.id
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide a channel ID or username (e.g., `/dump @PrivateDumpChannel`)."
            )
            return
        channel = context.args[0]
        self.dump_channels[user_id] = channel
        await update.message.reply_text(
            f"✅ Dump channel set to `{channel}`. Sorted files will be sent here too! "
            "Ensure the bot is added to the channel with send permissions.",
            parse_mode='Markdown'
        )
        username = update.effective_user.username or "Unknown"
        await self.log_action(context, user_id, username, "Set dump channel", f"Channel: {channel}")

    async def endsequence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /endsequence command"""
        user_id = update.effective_user.id
        if user_id not in self.user_sessions or not self.user_sessions[user_id]:
            await update.message.reply_text(
                "❌ No files received yet! Use `/sequence` first and send some video files."
            )
            return
        files = self.user_sessions[user_id]
        file_count = len(files)
        try:
            await update.message.reply_text(
                f"📊 Sequence added to queue. Received {file_count} files."
            )
        except Exception as e:
            logger.error(f"Failed to send queue confirmation: {e}")
            await update.message.reply_text("❌ Error confirming queue. Check logs for details.")
        username = update.effective_user.username or "Unknown"
        await self.log_action(context, user_id, username, "Ended sequence", f"Files received: {file_count}")
        # Filter valid files
        valid_files = [f for f in files if f.episode_number is not None and f.video_quality is not None]
        invalid_files = [f for f in files if f.episode_number is None or f.video_quality is None]
        if not valid_files:
            await update.message.reply_text(
                "❌ No valid files could be processed. Please check the file naming convention."
            )
            del self.user_sessions[user_id]
            return
        # Group and sort files by quality
        quality_groups = {480: [], 720: [], 1080: []}
        other_files = []
        for f in valid_files:
            if f.video_quality in quality_groups:
                quality_groups[f.video_quality].append(f)
            else:
                other_files.append(f)
        for quality in quality_groups:
            quality_groups[quality].sort(key=lambda x: x.episode_number)
        other_files.sort(key=lambda x: (x.episode_number, x.video_quality or 0))
        # Send sorted files by quality blocks to user and dump channel
        await update.message.reply_text("🔄 Sending sorted files by quality...")
        dump_chat_id = self.dump_channels.get(user_id)
        for quality in [480, 720, 1080]:
            if quality_groups[quality]:
                await update.message.reply_text(
                    f"📺 **{quality}P QUALITY EPISODES** 📺\n"
                    f"Sending {len(quality_groups[quality])} episodes in {quality}p quality...",
                    parse_mode='Markdown'
                )
                for video_file in quality_groups[quality]:
                    try:
                        if video_file.file_type == 'video':
                            await context.bot.send_video(
                                chat_id=update.effective_chat.id,
                                video=video_file.file_id,
                                caption=video_file.caption
                            )
                            if dump_chat_id:
                                await context.bot.send_video(
                                    chat_id=dump_chat_id,
                                    video=video_file.file_id,
                                    caption=video_file.caption
                                )
                                await asyncio.sleep(1)  # Delay for dump channel send
                        else:
                            await context.bot.send_document(
                                chat_id=update.effective_chat.id,
                                document=video_file.file_id,
                                caption=video_file.caption
                            )
                            if dump_chat_id:
                                await context.bot.send_document(
                                    chat_id=dump_chat_id,
                                    document=video_file.file_id,
                                    caption=video_file.caption
                                )
                                await asyncio.sleep(1)  # Delay for dump channel send
                    except Exception as e:
                        logger.error(f"Error sending file {video_file.caption or video_file.filename}: {e}")
                        await update.message.reply_text(
                            f"❌ Error sending file: {video_file.caption or video_file.filename}"
                        )
        if other_files:
            await update.message.reply_text(
                f"📺 **OTHER QUALITY EPISODES** 📺\n"
                f"Sending {len(other_files)} episodes with unknown quality...",
                parse_mode='Markdown'
            )
            for video_file in other_files:
                try:
                    if video_file.file_type == 'video':
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=video_file.file_id,
                            caption=video_file.caption
                        )
                        if dump_chat_id:
                            await context.bot.send_video(
                                chat_id=dump_chat_id,
                                video=video_file.file_id,
                                caption=video_file.caption
                            )
                            await asyncio.sleep(1)  # Delay for dump channel send
                    else:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=video_file.file_id,
                            caption=video_file.caption
                        )
                        if dump_chat_id:
                            await context.bot.send_document(
                                chat_id=dump_chat_id,
                                document=video_file.file_id,
                                caption=video_file.caption
                            )
                            await asyncio.sleep(1)  # Delay for dump channel send
                except Exception as e:
                    logger.error(f"Error sending file {video_file.caption or video_file.filename}: {e}")
                    await update.message.reply_text(
                        f"❌ Error sending file: {video_file.caption or video_file.filename}"
                    )
        # Generate summary message
        summary = await self.generate_summary(valid_files, file_count, quality_groups, other_files)
        await update.message.reply_text(summary, parse_mode='Markdown')
        # Clear the session
        del self.user_sessions[user_id]

    async def generate_summary(self, valid_files: List[VideoFile], total_files: int, quality_groups: Dict, other_files: List[VideoFile]) -> str:
        """Generate summary message with missing episodes info"""
        processed_count = len(valid_files)
        summary = "✅ **SORTING COMPLETE** ✅\n"
        summary += f"📊 {processed_count}/{total_files} files sorted by quality\n\n"
        # Quality block summary
        for quality in [480, 720, 1080]:
            if quality_groups[quality]:
                episodes = sorted([f.episode_number for f in quality_groups[quality]])
                episode_range = f"E{episodes[0]:02d}-E{episodes[-1]:02d}" if episodes else "None"
                summary += f"📺 {quality}p: {len(quality_groups[quality])} episodes ({episode_range})\n"
        if other_files:
            episodes = sorted([f.episode_number for f in other_files if f.episode_number])
            episode_range = f"E{episodes[0]:02d}-E{episodes[-1]:02d}" if episodes else "None"
            summary += f"📺 Other: {len(other_files)} episodes ({episode_range})\n"
        failed_count = total_files - processed_count
        if failed_count > 0:
            summary += f"\n\n❌ **{failed_count} files could not be processed** (invalid naming format)"
        summary += "\n\n🎉 Files sent in quality order: 480p → 720p → 1080p"
        return summary

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle document file uploads"""
        user_id = update.effective_user.id
        if user_id not in self.user_sessions:
            await update.message.reply_text(
                "❌ Please use `/sequence` first to start collecting files!"
            )
            return
        document = update.message.document
        if document:
            filename = document.file_name or "unknown_file"
            caption = update.message.caption or ''
            video_file = VideoFile(document.file_id, filename, caption, 'document')
            self.user_sessions[user_id].append(video_file)
            if video_file.episode_number is not None and video_file.video_quality is not None:
                status = f"✅ Episode {video_file.episode_number}, Quality {video_file.video_quality}p"
            else:
                status = "⚠️ Could not parse episode/quality info"
            await update.message.reply_text(
                f"📁 File received: `{filename}`\n{status}",
                parse_mode='Markdown'
            )
            username = update.effective_user.username or "Unknown"
            await self.log_action(context, user_id, username, "Uploaded document", f"File: {filename}")

    async def handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle video file uploads"""
        user_id = update.effective_user.id
        if user_id not in self.user_sessions:
            await update.message.reply_text(
                "❌ Please use `/sequence` first to start collecting files!"
            )
            return
        video = update.message.video
        if video:
            filename = video.file_name or f"video_{video.file_id[:8]}.mp4"
            caption = update.message.caption or ''
            video_file = VideoFile(video.file_id, filename, caption, 'video')
            self.user_sessions[user_id].append(video_file)
            if video_file.episode_number is not None and video_file.video_quality is not None:
                status = f"✅ Episode {video_file.episode_number}, Quality {video_file.video_quality}p"
            else:
                status = "⚠️ Could not parse episode/quality info"
            await update.message.reply_text(
                f"🎥 Video received: `{filename}`\n{status}",
                parse_mode='Markdown'
            )
            username = update.effective_user.username or "Unknown"
            await self.log_action(context, user_id, username, "Uploaded video", f"File: {filename}")

async def main():
    """Main function to run the bot"""
    if not BOT_TOKEN:
        print("❌ Error: BOT_TOKEN environment variable not set!")
        print("Set BOT_TOKEN in Render dashboard environment variables")
        return

    print("🤖 Video Sorter Bot is starting...")
    print("🌐 Render Deployment: Optimized for cloud hosting")
    print(f"📋 Log channel: {'✅ Set' if LOG_CHANNEL_ID else '❌ Not set'}")

    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Set up bot commands
    commands = [
        BotCommand("start", "Start the bot and get help"),
        BotCommand("sequence", "Start collecting video files"),
        BotCommand("endsequence", "Finish and sort the collected files"),
        BotCommand("dump", "Set a dump channel (e.g., /dump @Channel)"),
    ]
    await application.bot.set_my_commands(commands)

    # Initialize bot
    bot = VideoSorterBot()

    # Add handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("sequence", bot.sequence_command))
    application.add_handler(CommandHandler("endsequence", bot.endsequence_command))
    application.add_handler(CommandHandler("dump", bot.dump_command))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
    application.add_handler(MessageHandler(filters.VIDEO, bot.handle_video))

    print("✅ Bot is running! Press Ctrl+C to stop.")
    print("📱 Send `/sequence` to start collecting video files.")

    # Run the bot
    try:
        await application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
