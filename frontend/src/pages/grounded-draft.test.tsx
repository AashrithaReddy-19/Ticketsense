import {fireEvent,render,screen} from "@testing-library/react";
import {describe,expect,it,vi} from "vitest";
import type {GroundedDraft} from "../api/client";
import {Status,renderDraft} from "./TicketWorkspace";
const base={ticket_id:"t",draft_text:"Help [KB-001]",citations:[],evidence:[],provider:"deterministic-development",model:"evidence-template-v1",generation_status:"ready",citation_validation_status:"valid",validation:{valid:true},generation_error:null,insufficient_evidence:false,attempt_count:1} satisfies GroundedDraft;
describe("grounded draft states",()=>{
 it("shows draft ready",()=>{render(<Status draft={base}/>);expect(screen.getByText(/Draft ready/)).toBeTruthy()});
 it("shows insufficient evidence",()=>{render(<Status draft={{...base,insufficient_evidence:true}}/>);expect(screen.getByText(/Insufficient evidence/)).toBeTruthy()});
 it("shows validation failure",()=>{render(<Status draft={{...base,citation_validation_status:"invalid"}}/>);expect(screen.getByText(/Citation validation failed/)).toBeTruthy()});
 it("shows generation unavailable",()=>{render(<Status draft={{...base,generation_error:"failed"}}/>);expect(screen.getByText(/Generation unavailable/)).toBeTruthy()});
 it("maps an inline citation to its evidence callback",()=>{const locate=vi.fn();render(<div>{renderDraft("Follow this [KB-001].",locate)}</div>);fireEvent.click(screen.getByRole("button",{name:"[KB-001]"}));expect(locate).toHaveBeenCalledWith("KB-001")});
});
