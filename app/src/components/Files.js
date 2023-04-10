import React, {useContext, useState} from "react";
import {
    Button as SButton,
    CardContent,
    CardDescription,
    CardHeader,
    CardMeta,
    Checkbox,
    Container,
    Dropdown,
    Form,
    Image,
    Label,
    Modal,
    PlaceholderLine,
    TableCell,
    TableHeaderCell,
} from "semantic-ui-react";
import {
    CardGroupCentered,
    CardPoster,
    cardTitleWrapper,
    encodeMediaPath,
    ExternalCardLink,
    FileIcon,
    findPosterPath,
    humanFileSize,
    isoDatetimeToString,
    mimetypeColor,
    PageContainer,
    Paginator,
    PreviewLink,
    textEllipsis,
    useTitle
} from "./Common";
import {
    useFilesProgressInterval,
    usePages,
    useQuery,
    useSearchFiles,
    useSearchFilter,
    useSearchView
} from "../hooks/customHooks";
import {Route, Routes} from "react-router-dom";
import {CardPlacholder} from "./Placeholder";
import {ArchiveCard, ArchiveRowCells} from "./Archive";
import Grid from "semantic-ui-react/dist/commonjs/collections/Grid";
import {Media, StatusContext, ThemeContext} from "../contexts/contexts";
import {Button, Card, CardIcon, Icon, Placeholder, Progress, Segment} from "./Theme";
import {SelectableTable} from "./Tables";
import {VideoCard, VideoRowCells} from "./Videos";
import _ from 'lodash';
import {FileBrowser} from "./FileBrowser";
import {refreshDirectoryFiles, refreshFiles} from "../api";
import {useSubscribeEventName} from "../Events";
import {TagsSelector} from "../Tags";

function EbookCard({file}) {
    const {s} = useContext(ThemeContext);
    let {data} = file;

    const downloadUrl = `/download/${encodeMediaPath(file.primary_path)}`;
    const isEpub = file['mimetype'].startsWith('application/epub');
    const viewerUrl = isEpub ? `/epub.html?url=${downloadUrl}` : null;

    const color = mimetypeColor(file.mimetype);
    return <Card color={color}>
        <CardPoster file={file} preview={true}/>
        <CardContent {...s}>
            <CardHeader>
                <Container textAlign='left'>
                    <ExternalCardLink to={viewerUrl || downloadUrl}>
                        {cardTitleWrapper(data ? data.title : file.title)}
                    </ExternalCardLink>
                </Container>
            </CardHeader>
            <CardMeta>
                {data.creator ? <b {...s}>{data.creator}</b> : null}
                {file.size && <p {...s}>{humanFileSize(file.size)}</p>}
            </CardMeta>
        </CardContent>
    </Card>

}

function ImageCard({file}) {
    const {s} = useContext(ThemeContext);
    const url = `/media/${encodeMediaPath(file.primary_path)}`;

    return <Card color={mimetypeColor(file.mimetype)}>
        <PreviewLink file={file}>
            <CardPoster file={file}/>
        </PreviewLink>
        <CardContent {...s}>
            <CardHeader>
                <ExternalCardLink to={url} className='no-link-underscore card-link'>
                    <p>{textEllipsis(file.title || file.stem || file.primary_path)}</p>
                </ExternalCardLink>
            </CardHeader>
            <CardMeta {...s}>
                <p>{isoDatetimeToString(file.modified / 1000)}</p>
            </CardMeta>
            <CardDescription {...s}>
                <p>{humanFileSize(file.size)}</p>
            </CardDescription>
        </CardContent>
    </Card>
}

function FileCard({file}) {
    const {s} = useContext(ThemeContext);

    const isEbookType = file.mimetype && (
        file.mimetype.startsWith('application/epub') || file.mimetype.startsWith('application/x-mobipocket-ebook')
    );

    if (file.model === 'video') {
        return <VideoCard key={file['primary_path']} file={file}/>;
    } else if (file.model === 'archive') {
        return <ArchiveCard key={file['primary_path']} file={file}/>;
    } else if (file.mimetype && file.mimetype.startsWith('image/')) {
        return <ImageCard key={file['primary_path']} file={file}/>;
    } else if (isEbookType) {
        return <EbookCard key={file['primary_path']} file={file}/>;
    }

    const {data} = file;
    let author;
    if (data) {
        author = data['author'];
    }
    const downloadUrl = `/download/${encodeMediaPath(file.primary_path)}`;
    const color = mimetypeColor(file.mimetype);
    const size = file.size !== null && file.size !== undefined ? humanFileSize(file.size) : null;

    return <Card color={color}>
        <CardPoster to={downloadUrl} file={file}/>
        <CardContent {...s}>
            <CardHeader>
                <ExternalCardLink to={downloadUrl}>
                    {cardTitleWrapper(file.title || file.name || file.primary_path)}
                </ExternalCardLink>
            </CardHeader>
            {author && <b {...s}>{author}</b>}
            <p>{isoDatetimeToString(file.modified)}</p>
            <p>{size}</p>
        </CardContent>
    </Card>
}

export function FileCards({files}) {
    if (!_.isEmpty(files)) {
        return <CardGroupCentered>
            {files.map(i => <FileCard key={i['primary_path']} file={i}/>)}
        </CardGroupCentered>
    } else if (files && files.length === 0) {
        return <Segment>No results!</Segment>
    } else {
        return <CardGroupCentered><CardPlacholder/></CardGroupCentered>
    }
}

function ImageRowCells({file}) {
    const url = `/media/${encodeMediaPath(file.primary_path)}`;

    let poster = <FileIcon file={file} size='large'/>;
    if (file.size && file.size < 50000000) {
        // Image is less than 5mb, use it.
        poster = <Image wrapped src={url} width='50px'/>;
    }

    // Fragment for SelectableRow
    return <React.Fragment>
        <TableCell>
            <center>
                {poster}
            </center>
        </TableCell>
        <TableCell>
            <PreviewLink file={file}>
                <p>{textEllipsis(file.title || file.stem || file.primary_path)}</p>
            </PreviewLink>
        </TableCell>
    </React.Fragment>
}

export function EbookRowCells({file}) {
    let cover = <CardIcon><FileIcon file={file}/></CardIcon>;
    const posterPath = findPosterPath(file);
    if (posterPath) {
        const coverSrc = `/media/${encodeMediaPath(posterPath)}`;
        cover = <Image wrapped src={coverSrc} width='50px'/>;
    }

    // Fragment for SelectableRow
    return <React.Fragment>
        <TableCell>
            <center>{cover}</center>
        </TableCell>
        <TableCell>
            <PreviewLink file={file}>
                <FileRowTagIcon file={file}/>
                {textEllipsis(file.title || file.stem)}
            </PreviewLink>
        </TableCell>
    </React.Fragment>
}

function FileRow({file}) {
    const isEbookType = file.mimetype && (
        file.mimetype.startsWith('application/epub') || file.mimetype.startsWith('application/x-mobipocket-ebook')
    );

    if (file.model === 'video' && 'video' in file) {
        return <VideoRowCells file={file}/>;
    } else if (file.model === 'archive') {
        return <ArchiveRowCells file={file}/>;
    } else if (file.mimetype && file.mimetype.startsWith('image/')) {
        return <ImageRowCells file={file}/>;
    } else if (isEbookType) {
        return <EbookRowCells key={file['primary_path']} file={file}/>;
    }

    // Fragment for SelectableRow
    return <React.Fragment>
        <TableCell>
            <center><FileIcon file={file} size='large'/></center>
        </TableCell>
        <TableCell>
            <FileRowTagIcon file={file}/>
            <PreviewLink file={file}>{textEllipsis(file.title || file.name || file.stem)}</PreviewLink>
        </TableCell>
    </React.Fragment>
}

export function FileTable({files, selectOn, onSelect, footer, selectedKeys}) {
    if (!files) {
        return <Placeholder>
            <PlaceholderLine/>
            <PlaceholderLine/>
            <PlaceholderLine/>
        </Placeholder>
    } else if (files && files.length > 0) {
        const headerContents = ['Poster', 'Title'];
        const rows = files.map(i => <FileRow key={i['key']} file={i}/>);
        return <SelectableTable
            headerContents={headerContents}
            selectOn={selectOn}
            onSelect={onSelect}
            selectedKeys={selectedKeys}
            footer={footer}
            rows={rows}
        />;
    } else {
        return <Segment>No results!</Segment>
    }
}

export function FileRowTagIcon({file}) {
    if (file.tags && file.tags.length) {
        return <Label circular color='green' style={{padding: '0.5em', marginRight: '0.5em'}}>
            <Icon name='tag' style={{margin: 0}}/>
        </Label>;
    }
}

export function SearchViewButton() {
    const {view, setView} = useSearchView();

    if (view === 'list') {
        return <Button icon='th' onClick={() => setView('cards')}/>;
    }
    return <Button icon='browser' onClick={() => setView('list')}/>;
}

export function SearchLimitDropdown({limits = []}) {
    const {limit, setLimit} = usePages();
    const limitOptions = limits.map(i => {
        return {key: i, value: i, text: i.toString()}
    });

    return <Dropdown fluid selection
                     placeholder='Limit'
                     options={limitOptions}
                     value={limit || limitOptions[0]['value']}
                     onChange={(e, {value}) => setLimit(value)}
    />
}

export function FilesView(
    files,
    activePage,
    totalPages,
    selectElem,
    selectedKeys,
    onSelect,
    setPage,
    limitOptions = [12, 24, 48, 96],
) {
    const {view} = useSearchView();

    let selectButton;
    const [selectOn, setSelectOn] = React.useState(false);
    const toggleSelectOn = () => setSelectOn(!selectOn);
    const selectButtonDisabled = view !== 'list';
    if (selectOn) {
        selectButton = <Button active disabled={selectButtonDisabled} icon='checkmark box'
                               onClick={toggleSelectOn}/>;
    } else {
        selectButton = <Button icon='checkmark box' disabled={selectButtonDisabled}
                               onClick={toggleSelectOn}/>;
    }

    const paginator = <center style={{marginTop: '2em'}}>
        <Paginator activePage={activePage} totalPages={totalPages} onPageChange={setPage}/>
    </center>;

    let body;
    if (view === 'list') {
        const footer = selectOn && selectElem ?
            <>
                <TableHeaderCell colSpan='3'>{selectElem}</TableHeaderCell>
            </> : null;
        body = <FileTable
            files={files}
            selectOn={selectOn}
            onSelect={onSelect}
            footer={footer}
            selectedKeys={selectedKeys || []}
        />;
    } else {
        body = <FileCards files={files}/>;
    }

    const viewButton = <SearchViewButton/>
    const limitDropdown = <SearchLimitDropdown limits={limitOptions}/>;
    const tagQuerySelector = <TagsQuerySelector/>;

    return {
        body,
        paginator,
        selectButton,
        viewButton,
        limitDropdown,
        tagQuerySelector,
    }
}

export function SearchFilter({filters = [], modalHeader}) {
    const {filter, setFilter} = useSearchFilter();
    const [open, setOpen] = useState(false);

    const handleOpen = (e) => {
        if (e) {
            e.preventDefault();
        }
        setOpen(true);
    }

    const handleClear = (e) => {
        if (e) {
            e.preventDefault();
        }
        setFilter(null);
        setOpen(false);
    }

    const filterFields = filters.map(
        i => <Form.Field key={i['text']}>
            <Checkbox radio
                      label={i['text']}
                      name='searchFilterRadioGroup'
                      checked={filter === i['value']}
                      value={i['value']}
                      onChange={() => setFilter(i['value'])}
            />
        </Form.Field>
    );

    if (filters && filters.length > 0) {
        return <>
            <Modal open={open} onOpen={() => handleOpen()} onClose={() => setOpen(false)} closeIcon>
                {modalHeader || <Modal.Header>Filter</Modal.Header>}
                <Modal.Content>
                    <Form>
                        {filterFields}
                    </Form>
                </Modal.Content>
                <Modal.Actions>
                    <SButton onClick={handleClear} secondary>Clear</SButton>
                    <SButton onClick={() => setOpen(false)}>Close</SButton>
                </Modal.Actions>
            </Modal>
            <Button
                icon='filter'
                onClick={handleOpen}
                primary={!!filter}
            />
        </>
    }
    return <></>
}

export function TagsQuerySelector({onChange}) {
    // Creates  dropdown that the User can use to manipulate the tag query.
    const {searchParams, updateQuery} = useQuery();
    const activeTags = searchParams.getAll('tag');

    const localOnChange = (name) => {
        updateQuery({'tag': name});
        if (onChange) {
            onChange(name);
        }
    }

    return <TagsSelector hideGroup={true}
                         hideEdit={true}
                         active={activeTags && activeTags.length > 0}
                         selectedTagNames={activeTags}
                         onToggle={localOnChange}
                         style={{marginLeft: '0.3em', marginTop: '0.3em'}}
    />
}

export function FilesSearchView({
                                    showView = true,
                                    showSelect = false,
                                    emptySearch = false,
                                    model,
                                }) {
    const filterOptions = [
        {key: 'video', text: 'Video', value: 'video'},
        {key: 'archive', text: 'Archive', value: 'archive'},
        {key: 'pdf', text: 'PDF', value: 'pdf'},
        {key: 'ebook', text: 'eBook', value: 'ebook'},
        {key: 'audio', text: 'Audio', value: 'audio'},
        {key: 'image', text: 'Image', value: 'image'},
        {key: 'zip', text: 'ZIP', value: 'zip'},
        {key: 'model', text: '3D Model', value: 'model'},
    ];

    const {searchFiles, totalPages, activePage, setPage} = useSearchFiles(24, emptySearch, model);

    const {body, paginator, selectButton, viewButton, limitDropdown, tagQuerySelector} = FilesView(
        searchFiles,
        activePage,
        totalPages,
        setPage,
    );

    return <>
        <Media at='mobile'>
            <Grid>
                <Grid.Row>
                    {showSelect &&
                        <Grid.Column width={2}>{selectButton}</Grid.Column>}
                    {showView &&
                        <Grid.Column width={2}>{viewButton}</Grid.Column>}
                    <Grid.Column width={4}>{limitDropdown}</Grid.Column>
                    <Grid.Column width={2}>{tagQuerySelector}</Grid.Column>
                    <Grid.Column width={2}><SearchFilter filters={filterOptions}/></Grid.Column>
                </Grid.Row>
            </Grid>
        </Media>
        <Media greaterThanOrEqual='tablet'>
            <Grid>
                <Grid.Row>
                    {showSelect &&
                        <Grid.Column width={1}>{selectButton}</Grid.Column>}
                    {showView &&
                        <Grid.Column width={1}>{viewButton}</Grid.Column>}
                    <Grid.Column width={2}>{limitDropdown}</Grid.Column>
                    <Grid.Column width={1}>{tagQuerySelector}</Grid.Column>
                    <Grid.Column width={1}><SearchFilter filters={filterOptions}/></Grid.Column>
                </Grid.Row>
            </Grid>
        </Media>
        {body}
        {paginator}
    </>
}

export function FilesRefreshProgress() {
    const {progress} = useFilesProgressInterval();

    if (!progress) {
        return;
    }

    const {
        discovery,
        refreshing,
        modeling,
        indexing,
        cleanup,
        indexed,
        unindexed,
        counted_files,
        total_file_groups,
        modeled
    } = progress;

    if (refreshing) {
        // Default is Counting / Step 1.  Move progress bar toward the middle to avoid clipping out of the screen.
        let params = {value: Math.floor(counted_files / 5), total: counted_files, progress: 'ratio'};
        let label = 'Refresh: Counting';

        if (discovery) {
            params['value'] = total_file_groups;
            params['total'] = counted_files;
            label = 'Refresh: Discovery'
        } else if (modeling) {
            params['value'] = modeled;
            params['total'] = total_file_groups;
            label = 'Refresh: Modeling';
        } else if (indexing) {
            params['value'] = unindexed;
            params['total'] = unindexed + indexed;
            label = 'Refresh: Indexing';
        } else if (cleanup) {
            params['value'] = 3;
            params['total'] = 4;
            label = 'Refresh: Cleanup';
        }
        return <Progress active color='violet' {...params}>{label}</Progress>
    }
}

function FilesPage() {
    useTitle('Files');

    return <>
        <FilesRefreshProgress/>
        <FileBrowser/>
    </>;
}

export function FilesRoute() {
    return <PageContainer>
        <Routes>
            <Route path='/' exact element={<FilesPage/>}/>
        </Routes>
    </PageContainer>;
}

export function FilesRefreshButton() {
    const {status} = useContext(StatusContext);
    const refreshing = status && status['flags'] && status['flags'].indexOf('refreshing') >= 0;
    const refreshingDirectory = status && status['flags'] && status['flags'].indexOf('refreshing_directory') >= 0;

    const [loading, setLoading] = React.useState(false);

    const handleClick = async () => {
        setLoading(true);
        await refreshFiles();
    }

    // Clear loading when global refresh event completes.
    useSubscribeEventName('global_refresh_completed', () => setLoading(false));

    return <Button icon
                   labelPosition='left'
                   loading={loading || refreshing || refreshingDirectory}
                   onClick={handleClick}
                   disabled={loading || refreshing}>
        <Icon name='refresh'/>
        Refresh All
    </Button>;
}

export function DirectoryRefreshButton({directory}) {
    const {status} = useContext(StatusContext);
    const refreshing = status && status['flags'] && status['flags'].indexOf('refreshing') >= 0;
    const refreshingDirectory = status && status['flags'] && status['flags'].indexOf('refreshing_directory') >= 0;

    const [loading, setLoading] = React.useState(false);

    const handleClick = async () => {
        setLoading(true);
        await refreshDirectoryFiles(directory);
    }

    // Clear loading when global refresh event completes.
    useSubscribeEventName('global_refresh_completed', () => setLoading(false));
    useSubscribeEventName('directory_refresh_completed', () => setLoading(false));

    return <Button icon
                   labelPosition='left'
                   loading={loading || refreshing || refreshingDirectory}
                   onClick={handleClick}
                   disabled={loading || refreshing || refreshingDirectory}
    >
        <Icon name='refresh'/>
        Refresh Directory
    </Button>
}
