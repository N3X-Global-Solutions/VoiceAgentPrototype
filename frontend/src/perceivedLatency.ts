// Measures the latency the caller actually experiences in a browser call: from the
// moment your microphone goes quiet to the moment the agent's audio starts playing.
// Unlike the server numbers, this includes the end-of-speech wait, the network and
// the playback buffer. Use headphones: speaker echo can register as your voice.

const TICK_MS = 20
const USER_VOICE_RMS = 0.015 // mic speech is ~0.02-0.2, room noise ~0.002-0.01
const BOT_VOICE_RMS = 0.005 // agent audio is clean: silence is ~0
const BOT_QUIET_MS = 600 // agent counts as done speaking after this much silence
const MIN_USER_SPEECH_MS = 150 // ignore clicks, breaths and short noises

export class PerceivedLatencyProbe {
  private ctx = new AudioContext()
  private local?: AnalyserNode
  private remote?: AnalyserNode
  private timer?: number
  private buf = new Float32Array(512)
  private lastUserVoiceAt = 0
  private userSpoke = false
  private botAudible = false
  private lastBotVoiceAt = 0
  private greetingDone = false // measure turns only, never the greeting
  private voicedMs = 0
  private onMeasure: (ms: number) => void

  constructor(onMeasure: (ms: number) => void) {
    this.onMeasure = onMeasure
  }

  attach(track: MediaStreamTrack, which: 'local' | 'remote') {
    const analyser = this.ctx.createAnalyser()
    analyser.fftSize = this.buf.length
    this.ctx.createMediaStreamSource(new MediaStream([track])).connect(analyser)
    if (which === 'local') this.local = analyser
    else this.remote = analyser
    this.timer ??= window.setInterval(() => this.tick(), TICK_MS)
  }

  stop() {
    if (this.timer) window.clearInterval(this.timer)
    void this.ctx.close()
  }

  private level(analyser?: AnalyserNode): number {
    if (!analyser) return 0
    analyser.getFloatTimeDomainData(this.buf)
    let sum = 0
    for (const v of this.buf) sum += v * v
    return Math.sqrt(sum / this.buf.length)
  }

  private tick() {
    const now = performance.now()
    if (this.level(this.remote) > BOT_VOICE_RMS) {
      if (!this.botAudible) {
        this.botAudible = true
        if (this.userSpoke) {
          this.onMeasure(Math.round(now - this.lastUserVoiceAt))
          this.userSpoke = false
        }
      }
      this.lastBotVoiceAt = now
    } else if (this.botAudible && now - this.lastBotVoiceAt > BOT_QUIET_MS) {
      this.botAudible = false
      this.greetingDone = true
    }
    // Ignore the mic while the agent talks (echo / barge-in) and before the greeting
    // has finished; count only sustained voice, not a click or a breath.
    if (this.botAudible || !this.greetingDone) {
      this.voicedMs = 0
      return
    }
    if (this.level(this.local) > USER_VOICE_RMS) {
      this.voicedMs += TICK_MS
      if (this.voicedMs >= MIN_USER_SPEECH_MS) this.userSpoke = true
      this.lastUserVoiceAt = now
    } else if (now - this.lastUserVoiceAt > 300) {
      this.voicedMs = 0
    }
  }
}
