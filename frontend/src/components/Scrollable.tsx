import { ReactNode, useCallback, useEffect, useRef } from "react";

/**
 * 自绘滚动条的滚动容器。
 * 部分系统（Windows 辅助功能强制经典滚动条）无视页面的滚动条配色 CSS，
 * 会渲染白底原生条 —— 所以这里双保险：CSS 隐藏原生条 + 把原生条挤出
 * overflow:hidden 的外框裁掉，再用绝对定位的灰色拇指自绘，支持拖动。
 */
export default function Scrollable({
  className = "",
  contentClassName = "",
  ariaLabel,
  children,
}: {
  className?: string;
  contentClassName?: string;
  ariaLabel?: string;
  children: ReactNode;
}) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const thumbRef = useRef<HTMLDivElement>(null);

  const update = useCallback(() => {
    const el = scrollerRef.current;
    const th = thumbRef.current;
    if (!el || !th) return;
    const { scrollTop, scrollHeight, clientHeight } = el;
    if (scrollHeight <= clientHeight + 1) {
      th.style.opacity = "0";
      return;
    }
    const h = Math.max(32, (clientHeight / scrollHeight) * clientHeight);
    const top =
      (scrollTop / (scrollHeight - clientHeight)) * (clientHeight - h);
    th.style.opacity = "1";
    th.style.height = `${h}px`;
    th.style.transform = `translateY(${top}px)`;
  }, []);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    update();
    el.addEventListener("scroll", update, { passive: true });
    const ro = new ResizeObserver(update);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    return () => {
      el.removeEventListener("scroll", update);
      ro.disconnect();
    };
  }, [update]);

  const onThumbDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = scrollerRef.current;
    const th = thumbRef.current;
    if (!el || !th) return;
    e.preventDefault();
    th.setPointerCapture(e.pointerId);
    const startY = e.clientY;
    const startTop = el.scrollTop;
    const ratio =
      (el.scrollHeight - el.clientHeight) /
      Math.max(1, el.clientHeight - th.offsetHeight);
    const move = (ev: PointerEvent) => {
      el.scrollTop = startTop + (ev.clientY - startY) * ratio;
    };
    const up = () => {
      th.removeEventListener("pointermove", move);
      th.removeEventListener("pointerup", up);
    };
    th.addEventListener("pointermove", move);
    th.addEventListener("pointerup", up);
  };

  return (
    <div className={`relative overflow-hidden ${className}`}>
      <div
        ref={scrollerRef}
        aria-label={ariaLabel}
        className={`no-native-scrollbar h-full overflow-y-auto ${contentClassName}`}
        style={{ marginRight: -24, paddingRight: 24 }}
      >
        {children}
      </div>
      <div
        ref={thumbRef}
        onPointerDown={onThumbDown}
        aria-hidden
        className="absolute right-[2px] top-0 w-[6px] cursor-pointer rounded-full bg-[#4a4a55] opacity-0 transition-opacity hover:bg-[#5c5c68]"
      />
    </div>
  );
}
