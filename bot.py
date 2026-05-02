import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
from collections import deque
import os

# إعدادات البوت
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='.', intents=intents)

# قائمة التشغيل لكل سيرفر
queues = {}
current_songs = {}
loop_status = {}
volume_levels = {}

# إعدادات yt-dlp
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

class MusicControls(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.guild_id = ctx.guild.id

    @discord.ui.button(label='⏯️ Play/Pause', style=discord.ButtonStyle.primary, custom_id='pause')
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.response.send_message('⏸️ تم إيقاف الأغنية مؤقتاً', ephemeral=True, delete_after=3)
        elif voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message('▶️ تم استئناف التشغيل', ephemeral=True, delete_after=3)

    @discord.ui.button(label='⏭️ Skip', style=discord.ButtonStyle.primary, custom_id='skip')
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message('⏭️ تم تخطي الأغنية', ephemeral=True, delete_after=3)

    @discord.ui.button(label='⏮️ Back', style=discord.ButtonStyle.primary, custom_id='back')
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        if guild_id in current_songs and current_songs[guild_id]:
            if guild_id not in queues:
                queues[guild_id] = deque()
            queues[guild_id].appendleft(current_songs[guild_id])
            interaction.guild.voice_client.stop()
            await interaction.response.send_message('⏮️ رجوع للأغنية السابقة', ephemeral=True, delete_after=3)

    @discord.ui.button(label='🔁 Loop', style=discord.ButtonStyle.secondary, custom_id='loop')
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        loop_status[guild_id] = not loop_status.get(guild_id, False)
        status = '🔁 مفعل' if loop_status[guild_id] else '❌ معطل'
        await interaction.response.send_message(f'التكرار: {status}', ephemeral=True, delete_after=3)

    @discord.ui.button(label='⏹️ Stop', style=discord.ButtonStyle.danger, custom_id='stop')
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild.id
        if guild_id in queues:
            queues[guild_id].clear()
        if voice_client:
            await voice_client.disconnect()
            await interaction.response.send_message('⏹️ تم إيقاف التشغيل والخروج', ephemeral=True, delete_after=3)

    @discord.ui.button(label='🔊 UP', style=discord.ButtonStyle.success, custom_id='volume_up')
    async def volume_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.source:
            new_volume = min(voice_client.source.volume + 0.1, 2.0)
            voice_client.source.volume = new_volume
            volume_levels[interaction.guild.id] = new_volume
            await interaction.response.send_message(f'🔊 الصوت: {int(new_volume * 100)}%', ephemeral=True, delete_after=3)

    @discord.ui.button(label='🔉 DOWN', style=discord.ButtonStyle.success, custom_id='volume_down')
    async def volume_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.source:
            new_volume = max(voice_client.source.volume - 0.1, 0.0)
            voice_client.source.volume = new_volume
            volume_levels[interaction.guild.id] = new_volume
            await interaction.response.send_message(f'🔉 الصوت: {int(new_volume * 100)}%', ephemeral=True, delete_after=3)

    @discord.ui.button(label='🔀 Switch', style=discord.ButtonStyle.secondary, custom_id='switch')
    async def switch_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        if guild_id in queues and len(queues[guild_id]) > 0:
            queues[guild_id].rotate(1)
            await interaction.response.send_message('🔀 تم تبديل ترتيب القائمة', ephemeral=True, delete_after=3)

async def play_next(ctx):
    guild_id = ctx.guild.id
    
    if loop_status.get(guild_id, False) and guild_id in current_songs:
        url = current_songs[guild_id]
    elif guild_id in queues and queues[guild_id]:
        url = queues[guild_id].popleft()
        current_songs[guild_id] = url
    else:
        current_songs.pop(guild_id, None)
        await ctx.send('✅ انتهت قائمة التشغيل!')
        return

    try:
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
        
        volume = volume_levels.get(guild_id, 0.5)
        player.volume = volume
        
        def after_playing(error):
            if error:
                print(f'خطأ في التشغيل: {error}')
            asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        
        ctx.voice_client.play(player, after=after_playing)
        
        duration_text = f"{player.duration // 60}:{player.duration % 60:02d}" if player.duration else "غير معروف"
        
        embed = discord.Embed(
            title='🎵 الآن يتم التشغيل',
            description=f'**{player.title}**',
            color=discord.Color.blue()
        )
        embed.add_field(name='⏱️ المدة', value=duration_text, inline=True)
        embed.add_field(name='🔊 الصوت', value=f'{int(volume * 100)}%', inline=True)
        embed.add_field(name='🔁 التكرار', value='مفعل' if loop_status.get(guild_id, False) else 'معطل', inline=True)
        
        if player.thumbnail:
            embed.set_thumbnail(url=player.thumbnail)
        
        embed.set_footer(text=f'طلب بواسطة {ctx.author.name}', icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        
        view = MusicControls(ctx)
        await ctx.send(embed=embed, view=view)
        
    except Exception as e:
        await ctx.send(f'❌ حدث خطأ: {str(e)}')
        if guild_id in queues and queues[guild_id]:
            await play_next(ctx)

@bot.event
async def on_ready():
    print(f'🤖 البوت {bot.user} جاهز للعمل!')
    print(f'📊 متصل بـ {len(bot.guilds)} سيرفر')
    await bot.change_presence(activity=discord.Game(name='.publish | 🎵 TikTok Music'))

@bot.command(name='publish')
async def publish(ctx):
    """أمر تشغيل الأغاني من TikTok"""
    
    # التحقق من وجود المستخدم في روم صوتي
    if not ctx.author.voice:
        embed = discord.Embed(
            title='❌ خطأ',
            description='يجب أن تكون في روم صوتي أولاً!',
            color=discord.Color.red()
        )
        await ctx.send(embed=embed, delete_after=10)
        return
    
    # طلب الرابط
    embed = discord.Embed(
        title='🔗 أرسل رابط الفيديو',
        description='الرجاء إرسال رابط TikTok أو أي رابط فيديو آخر\n⏱️ لديك 60 ثانية',
        color=discord.Color.blue()
    )
    embed.set_footer(text='اكتب "cancel" للإلغاء')
    await ctx.send(embed=embed)
    
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel
    
    try:
        msg = await bot.wait_for('message', timeout=60.0, check=check)
        
        if msg.content.lower() == 'cancel':
            await ctx.send('❌ تم الإلغاء')
            return
        
        url = msg.content
        
        # الاتصال بالروم الصوتي
        voice_channel = ctx.author.voice.channel
        
        if ctx.voice_client is None:
            await voice_channel.connect()
        elif ctx.voice_client.channel != voice_channel:
            await ctx.voice_client.move_to(voice_channel)
        
        guild_id = ctx.guild.id
        
        # إضافة للقائمة
        if guild_id not in queues:
            queues[guild_id] = deque()
        
        queues[guild_id].append(url)
        
        # إذا لم يكن هناك تشغيل حالي، ابدأ التشغيل
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await play_next(ctx)
        else:
            embed = discord.Embed(
                title='✅ تمت الإضافة للقائمة',
                description=f'الموضع في القائمة: {len(queues[guild_id])}',
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
    
    except asyncio.TimeoutError:
        await ctx.send('⏱️ انتهى الوقت! الرجاء المحاولة مرة أخرى.')
    except Exception as e:
        await ctx.send(f'❌ حدث خطأ: {str(e)}')

@bot.command(name='queue')
async def queue_command(ctx):
    """عرض قائمة التشغيل"""
    guild_id = ctx.guild.id
    
    if guild_id not in queues or not queues[guild_id]:
        await ctx.send('📭 القائمة فارغة!')
        return
    
    embed = discord.Embed(
        title='📜 قائمة التشغيل',
        color=discord.Color.blue()
    )
    
    queue_list = list(queues[guild_id])
    for i, url in enumerate(queue_list[:10], 1):
        embed.add_field(name=f'{i}.', value=url[:50] + '...', inline=False)
    
    if len(queue_list) > 10:
        embed.set_footer(text=f'وهناك {len(queue_list) - 10} أغنية أخرى...')
    
    await ctx.send(embed=embed)

@bot.command(name='clear')
async def clear_queue(ctx):
    """مسح قائمة التشغيل"""
    guild_id = ctx.guild.id
    
    if guild_id in queues:
        queues[guild_id].clear()
        await ctx.send('🗑️ تم مسح القائمة!')
    else:
        await ctx.send('📭 القائمة فارغة بالفعل!')

@bot.command(name='help')
async def help_command(ctx):
    """عرض قائمة الأوامر"""
    embed = discord.Embed(
        title='📖 قائمة الأوامر',
        description='جميع أوامر البوت المتاحة',
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name='.publish',
        value='تشغيل أغنية من TikTok أو أي رابط',
        inline=False
    )
    embed.add_field(
        name='.queue',
        value='عرض قائمة التشغيل',
        inline=False
    )
    embed.add_field(
        name='.clear',
        value='مسح قائمة التشغيل',
        inline=False
    )
    
    embed.add_field(
        name='🎮 أزرار التحكم',
        value='⏯️ Play/Pause | ⏭️ Skip | ⏮️ Back\n🔁 Loop | ⏹️ Stop | 🔊 UP/DOWN\n🔀 Switch',
        inline=False
    )
    
    embed.set_footer(text='صنع بـ ❤️ لخدمتكم')
    
    await ctx.send(embed=embed)

# تشغيل البوت
if __name__ == '__main__':
    TOKEN = 'MTQ5OTg4ODkzODE4MDAxODMyNw.Gb8fzm.4wvQsVQw6TKZxdEu5L7QMxpWOMctTIXKXRxQjk'
    bot.run(TOKEN)