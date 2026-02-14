# Audio Recording Configuration & Troubleshooting Guide
NOTE: this is AI-generated, I will leave it in here for now, and refer back to it if I ever have to (NL, 14/02/26)

## Understanding Audio Recording Issues

When recordings stop prematurely or exhibit glitching/aliasing, it's typically caused by:

1. **Buffer Overflows/Underflows** - Audio data arriving faster than it can be processed
2. **USB Device Issues** - Device disconnection or power issues
3. **CPU Overload** - System can't keep up with audio processing
4. **Disk I/O Bottlenecks** - Can't write to disk fast enough

## Key Configuration Parameters

### `chunk_size` (Currently: 1024)

The number of audio frames processed per callback. This is the most critical parameter for stability.

**At 44100 Hz:**
- 1024 frames = ~23ms per chunk
- 2048 frames = ~46ms per chunk
- 4096 frames = ~93ms per chunk

#### Recommendations:

**For Raspberry Pi (or slower systems):**
```yaml
audio:
  chunk_size: 2048  # or 4096 for more stability
```

**Trade-offs:**
- ✅ **Larger chunk_size (2048-4096)**
  - More stable on slower CPUs
  - Fewer context switches and callbacks
  - More time for disk I/O
  - Better for long recordings
  - **RECOMMENDED for your use case**

- ❌ **Smaller chunk_size (512-1024)**
  - Lower latency (not needed for file recording)
  - More CPU overhead
  - Higher risk of buffer overflows
  - Only needed for real-time processing

### `sample_rate` (Currently: 44100)

**Options:**
- `44100` - CD quality, standard for music
- `48000` - Professional audio standard

**Your device supports:** 44100 Hz (default)

**Recommendation:** Keep at `44100` unless you need 48000 for specific post-processing requirements.

### `channels` (Currently: 1)

**Options:**
- `1` - Mono
- `2` - Stereo

**Your device supports:** 2 channels max

**Recommendation:**
- Use `1` for mono sources (single mic, one input)
- Use `2` only if you need stereo recording
- Mono uses 50% less disk space and processing power

## Optimizing for Stability

### Recommended Configuration for Pi/Embedded Systems

```yaml
audio:
  sample_rate: 44100
  channels: 1  # or 2 if you need stereo
  chunk_size: 4096  # Start here, can reduce to 2048 if stable
  device_index: null
  device_name: "Soundcraft 2-channel Audio Driv: USB Audio (hw:1,0)"

recording:
  local_storage_path: "/path/to/fast/storage"  # Use SSD if available
```

### System-Level Optimizations

#### 1. **USB Power Management**

Disable USB auto-suspend to prevent device disconnection:

```bash
# Check current USB power management
cat /sys/module/usbcore/parameters/autosuspend

# Disable USB autosuspend (add to /etc/rc.local or systemd)
echo -1 | sudo tee /sys/module/usbcore/parameters/autosuspend

# For specific device (find with lsusb)
echo on | sudo tee /sys/bus/usb/devices/1-1/power/level
```

#### 2. **CPU Governor**

Set CPU to performance mode:

```bash
# Check current governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# Set to performance
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

#### 3. **Storage Performance**

- Use fast storage (SSD preferred over SD card)
- Ensure sufficient free space (fragmentation can slow writes)
- Consider RAM disk for very long recordings (then copy to permanent storage)

#### 4. **Process Priority**

Run with higher priority:

```bash
# In your systemd service file:
Nice=-10
IOSchedulingClass=realtime
IOSchedulingPriority=0
```

## Interpreting the New Monitoring Data

### Web UI Statistics

When recording, the UI now shows:

1. **Duration** - How long you've been recording
2. **File Size** - Current recording size in MB
3. **Queue Size** - Number of audio chunks waiting to be written
   - Normal: 0-10
   - Warning: > 50 (disk writes falling behind)
   - Critical: > 100 (buffer overflow imminent)

4. **Overflows** - Count of buffer overflow events
   - Should be 0
   - Any value > 0 means you need to increase `chunk_size`

5. **Device Health** - USB device connection status
   - Healthy: Green
   - Disconnected: Red (check USB power/connection)

### Log File Analysis

The enhanced logging now shows:

```
Recording stats: Duration: 120.5s, Frames: 5,302,050, Bytes: 10,604,100 (10.11 MB),
Callbacks: 5,178, Queue: 2, Max Queue: 15, Overflows: 0, Underflows: 0
```

**What to look for:**

- **Overflows > 0**: Increase `chunk_size`
- **Queue growing large**: Disk I/O issue, check storage speed
- **No callbacks for 5s**: USB device issue or system freeze
- **USB health check failed**: Device disconnected, check power/cable

### PyAudio Status Codes

The callback now decodes status flags:

```
INPUT_OVERFLOW - Audio data arriving faster than processing
INPUT_UNDERFLOW - Unusual, indicates timing issues
```

## Troubleshooting Checklist

### Recording Stops Prematurely

1. **Check logs for:**
   ```bash
   grep -i "overflow\|error\|health" app.log
   ```

2. **Look for patterns:**
   - Overflows before stopping? → Increase `chunk_size`
   - USB health failures? → Check USB power/connection
   - High queue sizes? → Check disk I/O

3. **Test configuration changes:**
   - Increase `chunk_size` to 4096
   - Reduce `channels` to 1 if possible
   - Ensure USB device has stable power

### Glitching or Aliasing in Recordings

**Symptoms:** Crackling, pops, or distortion in audio

**Causes:**
1. **Buffer overflows during recording**
   - Solution: Increase `chunk_size`

2. **Input levels too high (clipping)**
   - Solution: Reduce input gain on mixer/interface

3. **Sample rate mismatch**
   - Solution: Ensure config matches device default (44100)

4. **USB interference**
   - Solution: Use shielded USB cable, avoid USB hubs

### System Resource Issues

Monitor while recording:

```bash
# CPU usage
top -p $(pgrep -f "python.*main.py")

# I/O wait
iostat -x 5

# USB errors
dmesg | grep -i usb | tail -20
```

## Testing Your Configuration

### Quick Test Procedure

1. **Start a recording** via web UI
2. **Monitor the stats panel** - watch for:
   - Queue size staying low (< 10)
   - Overflow count staying at 0
   - File size growing steadily
3. **Check logs every 30 seconds:**
   ```bash
   tail -f app.log | grep -i "stats\|overflow\|error"
   ```
4. **Record for at least 5 minutes** to ensure stability
5. **Check recording quality** - play back and listen for glitches

### Optimal Settings Test

Try these configurations in order until stable:

```yaml
# Test 1: Maximum stability (start here)
chunk_size: 4096

# Test 2: Balanced
chunk_size: 2048

# Test 3: Lower latency (only if Test 2 is perfectly stable)
chunk_size: 1024
```

Record for 10+ minutes with each setting and check:
- Zero overflows
- Queue size < 20
- No glitches in playback
- No premature stops

## Understanding Device Latency Values

From your device info:
```
defaultLowInputLatency: 0.008684807256235827   (~8.7 ms)
defaultHighInputLatency: 0.034829931972789115  (~34.8 ms)
```

These are **device-level buffers**, separate from your `chunk_size`:

- **Low latency**: Device uses ~384 frame internal buffer
- **High latency**: Device uses ~1536 frame internal buffer

For file recording (non-real-time), PyAudio will use high latency mode, which is more forgiving and stable.

## Summary Recommendations

### For Your Setup (Pi + Soundcraft Interface)

```yaml
audio:
  sample_rate: 44100
  channels: 1          # Use 1 unless you need stereo
  chunk_size: 4096     # Start here for maximum stability
  device_name: "Soundcraft 2-channel Audio Driv: USB Audio (hw:1,0)"
```

**Additional Steps:**
1. Disable USB auto-suspend
2. Set CPU governor to performance
3. Use fast storage (SSD preferred)
4. Monitor the web UI stats during recording
5. Check logs for overflow warnings
6. Test recordings for 15+ minutes to ensure stability

### When to Adjust

- **If still getting overflows with chunk_size=4096:**
  - Check USB power supply (may need powered hub)
  - Reduce sample rate to 22050 temporarily
  - Check for system background processes consuming CPU

- **If stable with chunk_size=4096:**
  - Can try reducing to 2048 for slightly more responsive disk writes
  - Only reduce to 1024 if you need very frequent file size updates

## Need More Help?

Check the logs with these commands:

```bash
# Recent errors
grep -i "error\|overflow\|warning" app.log | tail -50

# Recording statistics
grep "Recording stats:" app.log | tail -10

# USB device issues
grep -i "usb\|device" app.log | tail -20
```

Monitor in real-time:
```bash
tail -f app.log | grep --line-buffered -i "stats\|overflow\|error\|warning"
```
