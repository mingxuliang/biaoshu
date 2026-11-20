import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BILLING_EVENT, type BillingEventDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { hasPerm } from "@/lib/permissions";
import Modal from "./Modal";

/** 任一接口返回余额不足或企业到期时弹出，引导去费用中心。 */
export default function BillingGuard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [detail, setDetail] = useState<BillingEventDetail | null>(null);

  useEffect(() => {
    const handler = (e: Event) => setDetail((e as CustomEvent<BillingEventDetail>).detail);
    window.addEventListener(BILLING_EVENT, handler);
    return () => window.removeEventListener(BILLING_EVENT, handler);
  }, []);

  const canPay = hasPerm(user, "billing");
  const title = detail?.kind === "inactive" ? "企业服务已到期" : "积分不足";

  return (
    <Modal open={!!detail} title={title} onClose={() => setDetail(null)} width="max-w-md">
      <div className="flex gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-50 text-amber-600">
          <i className={detail?.kind === "inactive" ? "ri-time-line text-xl" : "ri-coin-line text-xl"}></i>
        </span>
        <div className="text-sm leading-6 text-foreground-700">
          <p>{detail?.message}</p>
          {!canPay && <p className="mt-1 text-xs text-foreground-500">请联系企业管理员充值或调整你的月度积分额度。</p>}
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button
          type="button"
          onClick={() => setDetail(null)}
          className="h-9 cursor-pointer rounded-lg border border-background-300 px-4 text-sm text-foreground-700 hover:bg-background-200"
        >
          知道了
        </button>
        {canPay && (
          <button
            type="button"
            onClick={() => {
              setDetail(null);
              navigate("/console/billing");
            }}
            className="h-9 cursor-pointer rounded-lg bg-primary-500 px-4 text-sm font-medium text-background-50 hover:bg-primary-600"
          >
            去费用中心
          </button>
        )}
      </div>
    </Modal>
  );
}
