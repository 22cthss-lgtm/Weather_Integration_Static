import { useEffect, useState } from "react";

export default function SourceImage({ image, alt = image.title, className = "detail-image cwa-detail-image" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [image.image_url]);
  return <>
    {!failed ? <img className={className} src={image.image_url} alt={alt} onError={() => setFailed(true)} /> : null}
    {failed ? <p className="status-message" role="status">
      此時次的官方圖片目前無法取得。<a href={image.source_url} target="_blank" rel="noreferrer">查看官方來源</a>
    </p> : null}
  </>;
}
