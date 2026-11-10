import { randomUuid } from '@hermes/shared'

import type { ComposerAttachment } from '@/store/composer'
import { readImageForRemoteAttach, type GatewayRequest } from '@/app/session/hooks/use-prompt-actions/utils'

import { getVisibleComposerSurfaceId, type ComposerTarget } from './focus'

export interface NeoSteerReceipt {
  protocol?: number
  status: 'delivered' | 'not_delivered' | 'unsupported' | 'idle' | 'unknown'
  request_id?: string
  session_id?: string
  execution_generation?: number
  image_count?: number
  reason?: string
}

interface Request {
  target: ComposerTarget
  surfaceId: string
  sessionId: string
  respond: (result: Promise<NeoSteerReceipt>) => void
}
const EVENT = 'hermes:neo-composer-strict-v1'

export function requestNeoStrictSteer(target: ComposerTarget | 'active' | null, sessionId: string): Promise<NeoSteerReceipt> {
  // The SDK resolves explicit session addresses. Never broadcast an active request to all tiles.
  if (!target || target === 'active') return Promise.resolve({ status: 'unsupported' })
  const surfaceId = getVisibleComposerSurfaceId(target)
  if (!surfaceId) return Promise.resolve({ status: 'unsupported' })
  let answer: Promise<NeoSteerReceipt> | undefined
  const detail: Request = { target, surfaceId, sessionId, respond: result => { answer ??= result } }
  window.dispatchEvent(new CustomEvent(EVENT, { detail }))
  return answer ?? Promise.resolve({ status: 'unsupported' })
}

export function onNeoStrictSteer(handler: (request: Request) => void): () => void {
  const listener = (event: Event) => handler((event as CustomEvent<Request>).detail)
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}

/** No draft mutation until a receipt matching every captured delivery field exists. */
export async function performNeoStrictSteer(opts: {
  sessionId: string
  text: string
  attachments: ComposerAttachment[]
  request: GatewayRequest
  stillCurrent: () => boolean
  readImage?: typeof readImageForRemoteAttach
}): Promise<NeoSteerReceipt> {
  const { sessionId, text, attachments, request, stillCurrent } = opts
  if (attachments.some(a => a.kind !== 'image')) {
    return { status: 'not_delivered', reason: 'Only image attachments are supported for strict steer' }
  }
  if (!text.trim() && !attachments.length) return { status: 'not_delivered', reason: 'Empty draft' }
  const capability = await request<{ protocol: number; strict_steer: boolean; execution_generation: number; image_mode: string }>(
    'neo.composer.capabilities', { protocol: 1, session_id: sessionId })
  if (capability.protocol !== 1 || capability.image_mode !== 'vision_analyze_reference') return { status: 'unsupported' }
  if (!capability.strict_steer) return { status: 'idle' }
  const generation = capability.execution_generation
  const images = []
  for (const attachment of attachments) {
    const image = await (opts.readImage ?? readImageForRemoteAttach)(attachment.path ?? '')
    if (!image) throw new Error(`Could not read ${attachment.label}; draft kept`)
    images.push({ content_base64: image.contentBase64, filename: image.filename })
  }
  if (!stillCurrent()) return { status: 'not_delivered', reason: 'Composer changed before delivery' }
  const requestId = randomUuid()
  const receipt = await request<NeoSteerReceipt>('neo.composer.steer', {
    protocol: 1, session_id: sessionId, request_id: requestId, execution_generation: generation,
    text, images, timeout_ms: 20000
  }, 25000)
  if (receipt.protocol !== 1 || receipt.request_id !== requestId || receipt.session_id !== sessionId ||
      receipt.execution_generation !== generation || receipt.image_count !== images.length) {
    return { status: 'unknown', reason: 'No matching delivery receipt; draft kept' }
  }
  return receipt
}
