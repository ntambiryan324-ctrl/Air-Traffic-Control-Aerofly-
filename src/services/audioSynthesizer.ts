export class AudioSynthesizer {
  private audioCtx: AudioContext | null = null;
  private voiceEnabled = true;
  private soundEffectsEnabled = true;

  constructor() {
    // AudioContext will be initialized on first user gesture
  }

  private getAudioContext(): AudioContext | null {
    if (typeof window === 'undefined') return null;
    if (!this.audioCtx) {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      if (AudioCtx) {
        this.audioCtx = new AudioCtx();
      }
    }
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
    return this.audioCtx;
  }

  setVoiceEnabled(val: boolean) {
    this.voiceEnabled = val;
  }

  getVoiceEnabled(): boolean {
    return this.voiceEnabled;
  }

  setSoundEffectsEnabled(val: boolean) {
    this.soundEffectsEnabled = val;
  }

  getSoundEffectsEnabled(): boolean {
    return this.soundEffectsEnabled;
  }

  /**
   * Play authentic radio mic click / squelch burst
   */
  playSquelch() {
    if (!this.soundEffectsEnabled) return;
    try {
      const ctx = this.getAudioContext();
      if (!ctx) return;

      const now = ctx.currentTime;
      // White noise buffer for squelch
      const bufferSize = ctx.sampleRate * 0.05; // 50ms burst
      const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) {
        data[i] = Math.random() * 2 - 1;
      }

      const noise = ctx.createBufferSource();
      noise.buffer = buffer;

      // Bandpass filter to sound like VHF aircraft radio
      const filter = ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.frequency.value = 2400;
      filter.Q.value = 3.0;

      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.05);

      noise.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);

      noise.start(now);
      noise.stop(now + 0.05);
    } catch {
      // Audio playback fails gracefully if blocked by autoplay policy
    }
  }

  /**
   * Play frequency switch chirp
   */
  playChirp() {
    if (!this.soundEffectsEnabled) return;
    try {
      const ctx = this.getAudioContext();
      if (!ctx) return;

      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.exponentialRampToValueAtTime(1760, now + 0.06);

      gain.gain.setValueAtTime(0.05, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.06);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(now);
      osc.stop(now + 0.06);
    } catch {
      // Audio fails gracefully
    }
  }

  /**
   * Text-to-Speech for ATC responses with radio style
   */
  speakATC(text: string) {
    if (!this.voiceEnabled || typeof window === 'undefined' || !window.speechSynthesis) {
      return;
    }

    try {
      window.speechSynthesis.cancel();
      this.playSquelch();

      // Clean ATC text for speech
      let speakText = text.replace(/^(CONTROL|TOWER|GROUND|CLEARANCE|APPROACH|DEPARTURE|CENTER|ATIS):\s*/i, '');
      // Make callsign letters phonetic
      speakText = speakText.replace(/FL(\d+)/g, 'Flight Level $1');

      const utterance = new SpeechSynthesisUtterance(speakText);
      utterance.rate = 1.05;
      utterance.pitch = 0.95;

      const voices = window.speechSynthesis.getVoices();
      // Try to find English voice
      const englishVoice =
        voices.find((v) => v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Guy') || v.name.includes('Google'))) ||
        voices.find((v) => v.lang.startsWith('en'));
      if (englishVoice) {
        utterance.voice = englishVoice;
      }

      utterance.onend = () => {
        this.playSquelch();
      };

      window.speechSynthesis.speak(utterance);
    } catch {
      // Ignore speech synthesis failures
    }
  }
}

export const audioSynthesizer = new AudioSynthesizer();
