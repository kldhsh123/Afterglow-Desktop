/* Afterglow's original Win32 control skin. Native controls retain their
 * keyboard, accessibility and command behavior; only their painting changes.
 * No networking, installation or registry operations live in this module. */
#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <uxtheme.h>

enum { PAGE=1, PRIMARY, SECONDARY, SEGMENT, EDIT, COPIES, CHECK, PROGRESS, MUTED, ACCENT, FRAME };
typedef struct { int role, hover, dpi; } Skin;
static const COLORREF paper=RGB(245,241,228), surface=RGB(251,247,233), ink=RGB(26,47,75);
static const COLORREF accent=RGB(139,90,43), line=RGB(218,211,194), muted=RGB(122,138,160);
static HBRUSH paperBrush, surfaceBrush, brandBrush;
static int px(Skin *s, int value) { return MulDiv(value,s->dpi,96); }

static void box(HDC dc, RECT r, COLORREF color, COLORREF border, int radius) {
    HBRUSH brush=CreateSolidBrush(color); HPEN pen=CreatePen(PS_SOLID,1,border);
    HGDIOBJ oldb=SelectObject(dc,brush),oldp=SelectObject(dc,pen);
    RoundRect(dc,r.left,r.top,r.right,r.bottom,radius,radius);
    SelectObject(dc,oldb); SelectObject(dc,oldp); DeleteObject(brush); DeleteObject(pen);
}
static void text(HDC dc, HWND window, RECT r, LPCWSTR value, COLORREF color, UINT flags) {
    HFONT font=(HFONT)SendMessageW(window,WM_GETFONT,0,0);
    HGDIOBJ previous=font?SelectObject(dc,font):0;
    SetBkMode(dc,TRANSPARENT); SetTextColor(dc,color);
    DrawTextW(dc,value,-1,&r,flags|DT_NOPREFIX);
    if(previous) SelectObject(dc,previous);
}
static void tick(HDC dc,int x,int y,int size,COLORREF color) {
    HPEN pen=CreatePen(PS_SOLID,2,color); HGDIOBJ old=SelectObject(dc,pen);
    MoveToEx(dc,x,y+size/2,0); LineTo(dc,x+size/3,y+size); LineTo(dc,x+size,y);
    SelectObject(dc,old); DeleteObject(pen);
}
static void paint(HWND window,HDC dc,Skin *s,RECT r) {
    WCHAR value[1024]; GetWindowTextW(window,value,1024);
    FillRect(dc,&r,paperBrush);
    if(s->role==PROGRESS) {
        PBRANGE range; SendMessageW(window,PBM_GETRANGE,FALSE,(LPARAM)&range);
        int current=(int)SendMessageW(window,PBM_GETPOS,0,0);
        box(dc,r,RGB(235,227,205),RGB(235,227,205),px(s,8));
        if(range.iHigh>range.iLow && current>range.iLow) {
            RECT fill=r; int bounded=current>range.iHigh?range.iHigh:current;
            fill.right=r.left+MulDiv(r.right-r.left,bounded-range.iLow,range.iHigh-range.iLow);
            box(dc,fill,accent,accent,px(s,8));
        }
        return;
    }
    if(s->role==COPIES) {
        int count=(int)SendMessageW(window,LB_GETCOUNT,0,0);
        int top=(int)SendMessageW(window,LB_GETTOPINDEX,0,0);
        int selected=(int)SendMessageW(window,LB_GETCURSEL,0,0);
        int height=(int)SendMessageW(window,LB_GETITEMHEIGHT,0,0);
        if(height<1) height=px(s,40);
        for(int i=top,y=0;i<count && y<r.bottom;i++,y+=height) {
            RECT row={px(s,1),y+px(s,2),r.right-px(s,9),y+height-px(s,3)};
            box(dc,row,i==selected?RGB(235,227,205):surface,i==selected?RGB(196,154,108):line,px(s,12));
            RECT dot={px(s,14),y+height/2-px(s,6),px(s,26),y+height/2+px(s,6)};
            box(dc,dot,i==selected?ink:surface,i==selected?ink:line,px(s,12));
            if(i==selected) tick(dc,px(s,17),y+height/2-px(s,3),px(s,6),surface);
            LRESULT length=SendMessageW(window,LB_GETTEXTLEN,i,0);
            if(length>=0 && length<1024) {
                SendMessageW(window,LB_GETTEXT,i,(LPARAM)value);
                RECT label={px(s,39),y,r.right-px(s,23),y+height};
                text(dc,window,label,value,ink,DT_LEFT|DT_VCENTER|DT_SINGLELINE|DT_PATH_ELLIPSIS);
            }
        }
        if(count*height>r.bottom) {
            RECT rail={r.right-px(s,4),px(s,3),r.right-px(s,1),r.bottom-px(s,3)};
            box(dc,rail,RGB(235,227,205),RGB(235,227,205),px(s,3));
            int visible=r.bottom/height; int thumbHeight=MulDiv(rail.bottom-rail.top,visible,count);
            RECT thumb=rail; thumb.top+=MulDiv(rail.bottom-rail.top-thumbHeight,top,count-visible); thumb.bottom=thumb.top+thumbHeight;
            box(dc,thumb,RGB(176,154,121),RGB(176,154,121),px(s,3));
        }
        return;
    }
    int enabled=IsWindowEnabled(window); LRESULT state=SendMessageW(window,BM_GETSTATE,0,0);
    if(s->role==CHECK) {
        RECT square={px(s,1),r.bottom/2-px(s,8),px(s,17),r.bottom/2+px(s,8)};
        int checked=SendMessageW(window,BM_GETCHECK,0,0)==BST_CHECKED;
        box(dc,square,checked?ink:surface,checked?ink:line,px(s,5));
        if(checked) tick(dc,px(s,5),r.bottom/2-px(s,4),px(s,8),surface);
        r.left=px(s,28); text(dc,window,r,value,enabled?ink:muted,DT_LEFT|DT_VCENTER|DT_SINGLELINE);
    } else {
        int selected=s->role==SEGMENT && SendMessageW(window,BM_GETCHECK,0,0)==BST_CHECKED;
        COLORREF bg=s->role==PRIMARY||selected?ink:surface;
        COLORREF fg=s->role==PRIMARY||selected?surface:ink;
        if(s->hover&&enabled) bg=s->role==PRIMARY||selected?RGB(48,70,94):RGB(235,227,205);
        if((state&BST_PUSHED)&&enabled) bg=s->role==PRIMARY||selected?RGB(20,38,59):RGB(224,213,192);
        if(!enabled){bg=RGB(235,231,218);fg=muted;}
        RECT body=r; body.left++;body.top++;body.right--;body.bottom--;
        if(s->role==PRIMARY&&enabled) {
            /* Match the website's restrained letter shadow, without bitmap
             * buttons or replacing the native button's input behavior. */
            body.bottom-=px(s,2);
            RECT shadow=body;shadow.top+=px(s,2);shadow.bottom+=px(s,2);
            box(dc,shadow,RGB(222,220,210),RGB(222,220,210),shadow.bottom-shadow.top);
        }
        box(dc,body,bg,s->role==PRIMARY||selected?bg:line,body.bottom-body.top);
        body.left+=px(s,8);body.right-=px(s,8);
        text(dc,window,body,value,fg,DT_CENTER|DT_VCENTER|DT_SINGLELINE|DT_END_ELLIPSIS);
    }
    if(GetFocus()==window && enabled) {
        RECT focus=r; InflateRect(&focus,-px(s,4),-px(s,4));
        HBRUSH transparent=(HBRUSH)GetStockObject(NULL_BRUSH); HGDIOBJ old=SelectObject(dc,transparent);
        HPEN pen=CreatePen(PS_DOT,1,accent);HGDIOBJ oldPen=SelectObject(dc,pen);
        RoundRect(dc,focus.left,focus.top,focus.right,focus.bottom,focus.bottom-focus.top,focus.bottom-focus.top);
        SelectObject(dc,oldPen);SelectObject(dc,old);DeleteObject(pen);
    }
}

static LRESULT CALLBACK skin_proc(HWND window,UINT message,WPARAM wp,LPARAM lp,UINT_PTR id,DWORD_PTR data) {
    Skin *s=(Skin*)data;
    if(message==WM_NCDESTROY){RemoveWindowSubclass(window,skin_proc,id);HeapFree(GetProcessHeap(),0,s);return DefSubclassProc(window,message,wp,lp);}
    if(message==WM_ERASEBKGND){
        RECT r;GetClientRect(window,&r);FillRect((HDC)wp,&r,s->role==EDIT?surfaceBrush:paperBrush);
        if(s->role==FRAME) {
            /* Continue the navy brand column through the action row. Dialog
             * units keep this aligned with the sidebar at the current DPI. */
            RECT column={0,0,168,0};MapDialogRect(window,&column);
            column.bottom=r.bottom;FillRect((HDC)wp,&column,brandBrush);
        }
        return 1;
    }
    if(s->role==PAGE||s->role==FRAME) {
        if(message==WM_CTLCOLORSTATIC||message==WM_CTLCOLORBTN||message==WM_CTLCOLOREDIT) {
            HWND control=(HWND)lp;DWORD_PTR value=0;COLORREF color=ink;
            if(GetWindowSubclass(control,skin_proc,1,&value)) {
                Skin *child=(Skin*)value;if(child->role==MUTED)color=muted;else if(child->role==ACCENT)color=accent;
            }
            SetTextColor((HDC)wp,color);SetBkMode((HDC)wp,TRANSPARENT);
            SetBkColor((HDC)wp,message==WM_CTLCOLOREDIT?surface:paper);
            return (LRESULT)(message==WM_CTLCOLOREDIT?surfaceBrush:paperBrush);
        }
        return DefSubclassProc(window,message,wp,lp);
    }
    if(s->role==MUTED||s->role==ACCENT)return DefSubclassProc(window,message,wp,lp);
    if(message==WM_MOUSEMOVE&&!s->hover){s->hover=1;TRACKMOUSEEVENT t={sizeof(t),TME_LEAVE,window,0};TrackMouseEvent(&t);InvalidateRect(window,0,FALSE);}
    if(message==WM_MOUSELEAVE){s->hover=0;InvalidateRect(window,0,FALSE);}
    if(s->role==COPIES&&message==WM_MOUSEWHEEL){
        int top=(int)SendMessageW(window,LB_GETTOPINDEX,0,0);
        top+=(short)HIWORD(wp)>0?-1:1;if(top<0)top=0;
        SendMessageW(window,LB_SETTOPINDEX,top,0);InvalidateRect(window,0,FALSE);return 0;
    }
    if((message==WM_PAINT||message==WM_PRINTCLIENT)&&s->role!=EDIT){
        PAINTSTRUCT ps;HDC screen=message==WM_PAINT?BeginPaint(window,&ps):(HDC)wp;
        RECT r;GetClientRect(window,&r);
        HDC dc=CreateCompatibleDC(screen);HBITMAP buffer=CreateCompatibleBitmap(screen,r.right,r.bottom);
        HGDIOBJ previous=SelectObject(dc,buffer);paint(window,dc,s,r);
        BitBlt(screen,0,0,r.right,r.bottom,dc,0,0,SRCCOPY);SelectObject(dc,previous);DeleteObject(buffer);DeleteDC(dc);
        if(message==WM_PAINT)EndPaint(window,&ps);return 0;
    }
    LRESULT result=DefSubclassProc(window,message,wp,lp);
    if(message==WM_PAINT&&s->role==EDIT){
        HDC dc=GetDC(window);RECT r;GetClientRect(window,&r);HGDIOBJ old=SelectObject(dc,GetStockObject(NULL_BRUSH));
        HPEN pen=CreatePen(PS_SOLID,1,GetFocus()==window?accent:line);HGDIOBJ oldp=SelectObject(dc,pen);
        RoundRect(dc,0,0,r.right,r.bottom,px(s,10),px(s,10));SelectObject(dc,oldp);SelectObject(dc,old);DeleteObject(pen);ReleaseDC(window,dc);
    }
    if(message==WM_ENABLE||message==WM_SETFOCUS||message==WM_KILLFOCUS||message==BM_SETSTATE||message==BM_SETCHECK||message==WM_KEYUP||message==WM_LBUTTONUP||message==WM_SETTEXT||message==PBM_SETPOS||message==PBM_DELTAPOS||message==PBM_SETRANGE32||message==LB_SETCURSEL||message==LB_SETTOPINDEX)InvalidateRect(window,0,FALSE);
    return result;
}

void WINAPI Attach(HWND window,int role) {
    if(!window)return;
    HIGHCONTRASTW hc={sizeof(hc),0,0};SystemParametersInfoW(SPI_GETHIGHCONTRAST,sizeof(hc),&hc,0);
    if(hc.dwFlags&HCF_HIGHCONTRASTON)return;
    if(!paperBrush){
        paperBrush=CreateSolidBrush(paper);surfaceBrush=CreateSolidBrush(surface);
        /* Exact background of installer-sidebar.bmp, so its continuation
         * below the artwork cannot appear as a separate footer tile. */
        brandBrush=CreateSolidBrush(RGB(36,60,83));
    }
    DWORD_PTR existing=0;
    if(GetWindowSubclass(window,skin_proc,1,&existing)){((Skin*)existing)->role=role;InvalidateRect(window,0,TRUE);return;}
    Skin *s=(Skin*)HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(Skin));if(!s)return;
    s->role=role;HDC dc=GetDC(window);s->dpi=GetDeviceCaps(dc,LOGPIXELSX);ReleaseDC(window,dc);
    /* Disable stock painting only for controls we actually draw. Disabling
     * themes on the parent dialog also gave it classic-looking caption buttons.
     * Keep Windows responsible for the normal title bar and its hit testing. */
    if(role!=PAGE&&role!=FRAME&&role!=MUTED&&role!=ACCENT)SetWindowTheme(window,L"",L"");
    if(role==EDIT||role==COPIES){
        LONG style=GetWindowLongW(window,GWL_STYLE);SetWindowLongW(window,GWL_STYLE,style&~(WS_BORDER|WS_VSCROLL));
        LONG ex=GetWindowLongW(window,GWL_EXSTYLE);SetWindowLongW(window,GWL_EXSTYLE,ex&~WS_EX_CLIENTEDGE);
        SetWindowPos(window,0,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_NOZORDER|SWP_FRAMECHANGED);
        if(role==EDIT)SendMessageW(window,EM_SETMARGINS,EC_LEFTMARGIN|EC_RIGHTMARGIN,MAKELPARAM(px(s,12),px(s,12)));
        else SendMessageW(window,LB_SETITEMHEIGHT,0,px(s,36));
    }
    if(!SetWindowSubclass(window,skin_proc,1,(DWORD_PTR)s)){HeapFree(GetProcessHeap(),0,s);return;}
    InvalidateRect(window,0,TRUE);
}
void WINAPI Refresh(HWND window) {RedrawWindow(window,0,0,RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN|RDW_UPDATENOW);}
static BOOL CALLBACK detach_child(HWND window,LPARAM unused) {
    DWORD_PTR data=0;(void)unused;
    if(GetWindowSubclass(window,skin_proc,1,&data)) {
        RemoveWindowSubclass(window,skin_proc,1);HeapFree(GetProcessHeap(),0,(void*)data);
    }
    return TRUE;
}
void WINAPI Detach(HWND window) {
    EnumChildWindows(window,detach_child,0);detach_child(window,0);
    if(paperBrush)DeleteObject(paperBrush);if(surfaceBrush)DeleteObject(surfaceBrush);if(brandBrush)DeleteObject(brandBrush);
    paperBrush=surfaceBrush=brandBrush=0;
}
