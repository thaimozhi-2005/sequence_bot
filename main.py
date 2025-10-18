#!/usr/bin/env python3
"""
Telegram Video Sorter Bot - Render.com Ready
A bot that sorts video files by episode number and quality with dump channel support
Optimized for Render deployment with HTTP health check server
"""
import os
import re
import logging
import asyncio
from typing import List, Dict, Optional
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from aiohttp import web
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION - USE ENVIRONMENT VARIABLES
# ============================================
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
PORT = int(os.getenv('PORT', '10000'))  # Render assigns this

# ============================================
# HTTP HEALTH CHECK SERVER FOR RENDER
# ============================================
async def health_check(request):
    """Health check endpoint for Render"""
    return web.json_response({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'bot': 'Video Sorter Bot',
        'version': '2.0'
    })

async def root_handler(request):
    """Root endpoint"""
    return web.Response(text="""
╔══════════════════════════════════════╗
║   VIDEO SORTER BOT - ACTIVE          ║
╚══════════════════════════════════════╝

Status: 🟢 Running
Server Time: {}
Port: {}

Bot is running successfully on Render! ✅
Health: /health

Features:
✅ Sort videos by episode & quality
✅ Dump channel support
✅ 480p/720p/1080p grouping
""".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), PORT), 
    content_type='text/plain')

async def start_http_server():
    """Start HTTP server for Render health checks"""
    app = web.Application()
    app.router.add_get('/', root_handler)
    app.router.add_get('/health', health_check)
    app.router.add_get('/status', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 HTTP server started on 0.0.0.0:{PORT}")
    return runner

# ============================================
# VIDEO FILE CLASS
# ============================================
class VideoFile:
    def __init__(self, file_id: str, filename: str, caption: Optional[str] = None, file_type: str = 'document'):
        self.file_id = file_id
        self.filename = filename
        self.caption = caption or ''
        self.file_type = file_type
        self.episode_number = self.extract_episode_number()
        self.video_quality = self.extract_video_quality()

    def extract_season_episode(self) -> Optional[tuple[int, int]]:
        """
        Extract season and episode numbers from filename.
        Supports formats:
        - [S01-E07] or [S1-E7]
        - S01E07 or S1E7
        - Season 1 Episode 7
        Returns: (season, episode) tuple or None
        """
        patterns = [
            r'\[S(\d+)-E(\d+)\]',           # [S01-E07]
            r'S(\d+)E(\d+)',                 # S01E07
            r'Season\s*(\d+)\s*Episode\s*(\d+)',  # Season 1 Episode 7
            r's(\d+)e(\d+)',                 # s01e07 (lowercase)
        ]
        
        for pattern in patterns:
            match = re.search(pattern, self.filename, re.IGNORECASE)
            if match:
                season = int(match.group(1))
                episode = int(match.group(2))
                return (season, episode)
        return None
    
    def extract_episode_number(self) -> Optional[int]:
        """Extract episode number from filename"""
        result = self.extract_season_episode()
        return result[1] if result else None
    
    def extract_season_number(self) -> Optional[int]:
        """Extract season number from filename"""
        result = self.extract_season_episode()
        return result[0] if result else None
    
    def extract_video_quality(self) -> Optional[int]:
        """
        Extract video quality from filename.
        Supports formats:
        - [1080p] or [1080]
        - 1080p (standalone)
        Returns: quality as integer (e.g., 1080) or None
        """
        common_qualities = [144, 240, 360, 480, 720, 1080, 1440, 2160, 4320]
        
        patterns = [
            r'\[(\d+)p?\]',                  # [1080p] or [1080]
            r'(\d+)p(?:\s|$|\.)',            # 1080p (standalone)
            r'_(\d+)p_',                     # _1080p_
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, self.filename, re.IGNORECASE)
            for match in matches:
                quality = int(match)
                if quality in common_qualities:
                    return quality
        return None
    
    def parse_all(self) -> dict:
        """Parse all information from filename"""
        return {
            'filename': self.filename,
            'season': self.extract_season_number(),
            'episode': self.extract_episode_number(),
            'quality': self.extract_video_quality()
        }

    def __str__(self):
        return f"Episode {self.episode_number}, Quality {self.video_quality}: {self.filename}"

# ============================================
# VIDEO SORTER BOT CLASS
# ============================================
class VideoSorterBot:
    def __init__(self):
        self.user_sessions: Dict[int, List[VideoFile]] = {}
        self.dump_channels: Dict[int, str] = {}  # Store dump channel ID or username per user

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = (
            "🎬 **Video Sorter Bot v2.0** 🎬\n\n"
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
            "**File format expected:** `[S01-E07] Show Name [1080] [Single].mkv`\n\n"
            "🌐 Running on Render.com\n"
            "✅ Always online, never sleeps!\n\n"
            "Ready to get started? Use `/sequence` to begin!"
        )
        await update.message.reply_text(welcome_message, parse_mode='Markdown')

    async def sequence_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /sequence command"""
        user_id = update.effective_user.id
        self.user_sessions[user_id] = []

        message = (
            "📁 **Ready to receive files!** 📁\n\n"
            "Please start sending me your video files. I'll collect them and sort them "
            "when you use `/endsequence`.\n\n"
            "**Tip:** Make sure your files follow the naming convention:\n"
            "`[S01-E07] Show Name [Quality] [Single].extension`"
        )
        await update.message.reply_text(message, parse_mode='Markdown')

    async def dump_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /dump command to set a dump channel"""
        user_id = update.effective_user.id
        if not context.args:
            await update.message.reply_text(
                "❌ Please provide a channel ID or username.\n\n"
                "**Examples:**\n"
                "• `/dump @YourChannelUsername`\n"
                "• `/dump -1001234567890` (for private channels)\n\n"
                "**Note:** Make sure to add the bot to the channel as an admin with send message permissions!"
            )
            return

        channel = context.args[0]
        
        # Test if bot can send to the channel
        try:
            test_message = await context.bot.send_message(
                chat_id=channel,
                text="🔧 **Dump Channel Test**\n\nThis channel has been set as your dump channel for sorted video files!"
            )
            # Delete the test message after a few seconds
            await asyncio.sleep(3)
            await context.bot.delete_message(chat_id=channel, message_id=test_message.message_id)
            
            self.dump_channels[user_id] = channel
            await update.message.reply_text(
                f"✅ **Dump channel successfully set!**\n\n"
                f"Channel: `{channel}`\n"
                f"All sorted files will now be sent to this channel along with your chat.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error testing dump channel {channel}: {e}")
            await update.message.reply_text(
                f"❌ **Failed to set dump channel!**\n\n"
                f"Error: {str(e)}\n\n"
                f"**Please ensure:**\n"
                f"• The bot is added to the channel\n"
                f"• The bot has admin permissions\n"
                f"• The channel ID/username is correct"
            )

    async def send_file_to_dump(self, context: ContextTypes.DEFAULT_TYPE, dump_chat_id: str, video_file: VideoFile):
        """Send a file to the dump channel with error handling"""
        try:
            if video_file.file_type == 'video':
                await context.bot.send_video(
                    chat_id=dump_chat_id,
                    video=video_file.file_id,
                    caption=video_file.caption
                )
            else:
                await context.bot.send_document(
                    chat_id=dump_chat_id,
                    document=video_file.file_id,
                    caption=video_file.caption
                )
            await asyncio.sleep(0.5)  # Small delay to prevent hitting rate limits
            return True
        except Exception as e:
            logger.error(f"Error sending file to dump channel {dump_chat_id}: {video_file.filename} - {e}")
            return False

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

        await update.message.reply_text(
            f"📊 Processing {file_count} files and sorting by quality..."
        )

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

        # Sort files within each quality group by episode number
        for quality in quality_groups:
            quality_groups[quality].sort(key=lambda x: x.episode_number)

        other_files.sort(key=lambda x: (x.episode_number, x.video_quality or 0))

        # Get dump channel info
        dump_chat_id = self.dump_channels.get(user_id)
        dump_failed_files = []

        # Send sorted files by quality blocks
        await update.message.reply_text("🔄 **Starting file distribution...**")

        # Send files to dump channel first (if configured), then to user
        for quality in [480, 720, 1080]:
            if quality_groups[quality]:
                # Send quality header message to user
                await update.message.reply_text(
                    f"📺 **{quality}P QUALITY EPISODES** 📺\n"
                    f"Sending {len(quality_groups[quality])} episodes in {quality}p quality...",
                    parse_mode='Markdown'
                )
                
                # Send quality header message to dump channel
                if dump_chat_id:
                    try:
                        await context.bot.send_message(
                            chat_id=dump_chat_id,
                            text=f"📺 **{quality}P EPISODES** 📺\n"
                                 f"Uploading {len(quality_groups[quality])} episodes in {quality}p quality...",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Error sending header to dump channel: {e}")

                # Send each file
                for video_file in quality_groups[quality]:
                    # Send to user
                    try:
                        if video_file.file_type == 'video':
                            await context.bot.send_video(
                                chat_id=update.effective_chat.id,
                                video=video_file.file_id,
                                caption=video_file.caption
                            )
                        else:
                            await context.bot.send_document(
                                chat_id=update.effective_chat.id,
                                document=video_file.file_id,
                                caption=video_file.caption
                            )
                    except Exception as e:
                        logger.error(f"Error sending file to user {video_file.caption or video_file.filename}: {e}")

                    # Send to dump channel
                    if dump_chat_id:
                        success = await self.send_file_to_dump(context, dump_chat_id, video_file)
                        if not success:
                            dump_failed_files.append(video_file.filename)

        # Handle other quality files
        if other_files:
            await update.message.reply_text(
                f"📺 **OTHER QUALITY EPISODES** 📺\n"
                f"Sending {len(other_files)} episodes with other quality levels...",
                parse_mode='Markdown'
            )
            
            if dump_chat_id:
                try:
                    await context.bot.send_message(
                        chat_id=dump_chat_id,
                        text=f"📺 **OTHER QUALITY EPISODES** 📺\n"
                             f"Uploading {len(other_files)} episodes with various quality levels...",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Error sending other quality header to dump channel: {e}")

            for video_file in other_files:
                # Send to user
                try:
                    if video_file.file_type == 'video':
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=video_file.file_id,
                            caption=video_file.caption
                        )
                    else:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=video_file.file_id,
                            caption=video_file.caption
                        )
                except Exception as e:
                    logger.error(f"Error sending other quality file to user {video_file.caption or video_file.filename}: {e}")

                # Send to dump channel
                if dump_chat_id:
                    success = await self.send_file_to_dump(context, dump_chat_id, video_file)
                    if not success:
                        dump_failed_files.append(video_file.filename)

        # Send completion message to dump channel
        if dump_chat_id:
            try:
                completion_msg = (
                    "✅ **SORTING COMPLETE** ✅\n\n"
                    f"📊 Total files processed: {len(valid_files)}\n"
                    f"📁 Files organized by quality and episode number\n\n"
                    f"🎯 **Quality Distribution:**\n"
                )
                
                for quality in [480, 720, 1080]:
                    if quality_groups[quality]:
                        episodes = sorted([f.episode_number for f in quality_groups[quality]])
                        episode_range = f"E{episodes[0]:02d}-E{episodes[-1]:02d}" if episodes else "None"
                        completion_msg += f"• {quality}p: {len(quality_groups[quality])} episodes ({episode_range})\n"
                
                if other_files:
                    episodes = sorted([f.episode_number for f in other_files if f.episode_number])
                    episode_range = f"E{episodes[0]:02d}-E{episodes[-1]:02d}" if episodes else "None"
                    completion_msg += f"• Other: {len(other_files)} episodes ({episode_range})\n"
                
                completion_msg += "\n🎉 All episodes delivered successfully!"
                
                await context.bot.send_message(
                    chat_id=dump_chat_id,
                    text=completion_msg,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Error sending completion message to dump channel: {e}")

        # Generate summary message for user
        summary = await self.generate_summary(valid_files, file_count, quality_groups, other_files, dump_failed_files)
        await update.message.reply_text(summary, parse_mode='Markdown')

        # Clear the session
        del self.user_sessions[user_id]

    async def generate_summary(self, valid_files: List[VideoFile], total_files: int, quality_groups: Dict, other_files: List[VideoFile], dump_failed_files: List[str]) -> str:
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
            summary += f"\n❌ **{failed_count} files could not be processed** (invalid naming format)"

        if dump_failed_files:
            summary += f"\n⚠️ **{len(dump_failed_files)} files failed to send to dump channel**"

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

# ============================================
# MAIN FUNCTION
# ============================================
async def main():
    """Main function to run the bot"""
    logger.info("=" * 50)
    logger.info("🎬 Video Sorter Bot v2.0 Starting...")
    logger.info("🌐 Optimized for Render.com")
    logger.info("=" * 50)

    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
        logger.error("❌ BOT_TOKEN environment variable not set!")
        logger.error("Please set: BOT_TOKEN=your_bot_token")
        return

    try:
        # START HTTP SERVER FIRST (CRITICAL FOR RENDER!)
        logger.info(f"🌐 Starting HTTP server on 0.0.0.0:{PORT}...")
        http_runner = await start_http_server()
        logger.info(f"✅ HTTP server running on port {PORT}")
        
        # Create bot application
        logger.info("🤖 Initializing bot...")
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Register bot commands for menu
        commands = [
            BotCommand("start", "Start the bot and get help"),
            BotCommand("sequence", "Start collecting video files"),
            BotCommand("endsequence", "Finish and sort the collected files"),
            BotCommand("dump", "Set a dump channel (e.g., /dump @Channel)"),
        ]
        
        bot = VideoSorterBot()

        # Add command handlers
        application.add_handler(CommandHandler("start", bot.start_command))
        application.add_handler(CommandHandler("sequence", bot.sequence_command))
        application.add_handler(CommandHandler("endsequence", bot.endsequence_command))
        application.add_handler(CommandHandler("dump", bot.dump_command))
        application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_document))
        application.add_handler(MessageHandler(filters.VIDEO, bot.handle_video))

        # Set bot commands for UI menu
        await application.bot.set_my_commands(commands)
        logger.info("✅ Bot commands registered")
        
        logger.info("=" * 50)
        logger.info("✅ Bot is ready!")
        logger.info(f"🔗 Health check: http://0.0.0.0:{PORT}/health")
        logger.info("=" * 50)
        
        # Start polling
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        # Keep running
        logger.info("🟢 Bot is now running... Press Ctrl+C to stop")
        
        # Run forever
        while True:
            await asyncio.sleep(3600)
            
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise
    finally:
        if 'http_runner' in locals():
            await http_runner.cleanup()
            logger.info("🌐 HTTP server stopped")
        if 'application' in locals():
            await application.stop()
            await application.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
