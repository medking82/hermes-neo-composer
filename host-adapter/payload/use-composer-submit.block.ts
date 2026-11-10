  // neo-composer:strict-steer:v1 begin
  const strictInFlight = useRef(false)
  useLayoutEffect(() => onNeoStrictSteer(request => {
    if (request.target !== scope.target || request.surfaceId !== surfaceId || !paneVisible ||
        (request.sessionId !== sessionId && request.sessionId !== draftScopeRef.current)) return
    const run = async (): Promise<NeoSteerReceipt> => {
      if (strictInFlight.current) return { status: 'not_delivered', reason: 'Strict steer already in progress' }
      if (!busy) return { status: 'idle' }
      if (inputDisabled || disabled || queueEdit) return { status: 'not_delivered', reason: 'Composer unavailable' }
      const gateway = $gateway.get()
      if (!gateway || !sessionId) return { status: 'unsupported' }
      const capturedScope = draftScopeRef.current
      if (editorRef.current) draftRef.current = composerPlainText(editorRef.current)
      const text = draftRef.current
      const captured = [...scope.attachments.$attachments.get()]
      const destination = captureSubmissionDestination(sessionId, gateway.request.bind(gateway))
      const stillCurrent = () => draftScopeRef.current === capturedScope && draftRef.current === text &&
        (!editorRef.current || composerPlainText(editorRef.current) === text) &&
        captured.length === scope.attachments.$attachments.get().length &&
        captured.every((a, i) => a === scope.attachments.$attachments.get()[i])
      strictInFlight.current = true
      try {
        const receipt = await performNeoStrictSteer({ sessionId, text: pathifyRefs(text), attachments: captured,
          request: destination.requestGateway, stillCurrent })
        if (receipt.status === 'delivered' && stillCurrent()) {
          clearDraft()
          scope.attachments.removeOccurrences(captured)
          stashAt(capturedScope, '', [])
        }
        return receipt
      } catch (error) {
        return { status: 'unknown', reason: error instanceof Error ? error.message : String(error) }
      } finally {
        strictInFlight.current = false
      }
    }
    request.respond(run())
  }))
  // neo-composer:strict-steer:v1 end

