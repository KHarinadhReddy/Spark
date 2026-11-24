import { useEffect, useRef, useState } from "react";
import { ActionCard } from "./ActionCard";
import { FlagBanner, Sources } from "./Sources";
import { COPY } from "../i18n";
import { ArrowRightIcon, MicIcon, SendIcon, SparkIcon, VolumeIcon } from "../icons";

export function ChatView({
  t,
  language,
  config,
  messages,
  actionMap,
  actionBusy,
  thinking,
  mic,
  onSend,
  onMic,
  onApprove,
  onReject,
  onUndo,
  onSpeak,
}) {
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, thinking, mic]);

  const suggestions =
    language === "hi" ? t.suggestions : config?.prompts?.slice(0, 6) || t.suggestions;

  function submit(event) {
    event.preventDefault();
    const text = input.trim();
    if (!text || thinking) return;
    setInput("");
    onSend(text);
  }

  function onKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit(event);
    }
  }

  const waiting = mic === "listening" ? t.listening : mic === "transcribing" ? t.transcribing : null;

  return (
    <div className="page chat-page">
      <header className="page-head chat-head">
        <div>
          <p className="eyebrow">{t.quickAsk}</p>
          <h1>{t.chatTitle}</h1>
          <p>{t.chatSub}</p>
        </div>
        <span className="head-mark">
          <SparkIcon size={26} />
        </span>
      </header>

      <section className="chat-panel" aria-live="polite">
        <div className="chat-scroll" ref={scrollRef}>
          {messages.length === 0 ? (
            <div className="chat-welcome">
              <span className="welcome-mark">
                <SparkIcon size={38} />
              </span>
              <h2>{t.welcomeTitle}</h2>
              <p>{t.welcomeSub}</p>
              <div className="suggestion-grid">
                {suggestions.map((suggestion) => (
                  <button
                    type="button"
                    key={suggestion}
                    className="suggestion"
                    onClick={() => onSend(suggestion)}
                    disabled={thinking}
                  >
                    <SparkIcon size={15} />
                    <span>{suggestion}</span>
                    <ArrowRightIcon size={15} />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <article key={message.id} className={`msg ${message.role}`}>
                {message.role === "assistant" && (
                  <span className="avatar">
                    <SparkIcon size={18} />
                  </span>
                )}
                <div className="msg-body">
                  <div className={`bubble ${message.error ? "error" : ""}`}>
                    <p>{message.text}</p>
                  </div>
                  {message.cardIds?.length > 0 && (
                    <div className="cards">
                      {message.cardIds.map((id) =>
                        actionMap[id] ? (
                          <ActionCard
                            key={id}
                            action={actionMap[id]}
                            language={message.language || language}
                            onApprove={onApprove}
                            onReject={onReject}
                            onUndo={onUndo}
                            busy={Boolean(actionBusy[id])}
                          />
                        ) : null,
                      )}
                    </div>
                  )}
                  {message.flags?.length > 0 && (
                    <FlagBanner flags={message.flags} language={message.language || language} />
                  )}
                  {message.sources?.length > 0 && (
                    <Sources sources={message.sources} language={language} />
                  )}
                  {message.role === "assistant" && !message.error && (
                    <button
                      type="button"
                      className="speak-btn"
                      onClick={() => onSpeak(message.text, message.language || language)}
                    >
                      <VolumeIcon size={14} />
                      {t.speakReply}
                    </button>
                  )}
                </div>
              </article>
            ))
          )}

          {thinking && (
            <article className="msg assistant">
              <span className="avatar">
                <SparkIcon size={18} />
              </span>
              <div className="typing" aria-label={t.thinking}>
                <span />
                <span />
                <span />
              </div>
            </article>
          )}
          <div ref={endRef} />
        </div>

        <div className="composer-wrap">
          <form className="composer" onSubmit={submit}>
            <div className="composer-inner">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder={t.askPlaceholder}
                rows={1}
                aria-label={t.askPlaceholder}
                maxLength={2000}
              />
              <button
                type="button"
                className={`mic-btn ${mic}`}
                onClick={onMic}
                aria-label={t.listening}
                title={t.listening}
              >
                <MicIcon size={20} />
              </button>
              <button
                type="submit"
                className="send-btn"
                disabled={!input.trim() || thinking}
                aria-label={t.send}
              >
                <SendIcon size={18} />
              </button>
            </div>
            <div className="composer-hint">
              {waiting || (thinking ? t.thinking : t.chatSub)}
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
