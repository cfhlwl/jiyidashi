import type { VoiceSubmissionPhase } from './voiceCapture'

export type ElderRememberState =
  | 'IDLE'
  | 'RECORDING'
  | 'RECORDED'
  | 'UPLOADING'
  | 'VERIFYING'
  | 'TRANSCRIBING'
  | 'SAVED'
  | 'FAILED'

export function deriveElderRememberState(input: {
  recording: boolean
  hasClip: boolean
  memorySaved: boolean
  submitting: boolean
  phase: VoiceSubmissionPhase
  hasError: boolean
}): ElderRememberState {
  if (input.recording) return 'RECORDING'
  if (input.memorySaved) return 'SAVED'
  if (input.hasError || input.phase === 'failed') return 'FAILED'
  if (input.submitting) {
    if (input.phase === 'uploading') return 'UPLOADING'
    if (input.phase === 'verifying') return 'VERIFYING'
    if (input.phase === 'transcribing') return 'TRANSCRIBING'
    if (input.phase === 'saved') return 'SAVED'
  }
  if (input.hasClip) return 'RECORDED'
  return 'IDLE'
}

export function elderRememberStateLabel(state: ElderRememberState): string {
  switch (state) {
    case 'IDLE':
      return '准备好了，点“开始说”'
    case 'RECORDING':
      return '正在听你说'
    case 'RECORDED':
      return '已经录好了'
    case 'UPLOADING':
      return '正在上传'
    case 'VERIFYING':
      return '正在验证录音'
    case 'TRANSCRIBING':
      return '正在转成文字并保存'
    case 'SAVED':
      return '已经记住了'
    case 'FAILED':
      return '这次没有保存成功'
  }
}
